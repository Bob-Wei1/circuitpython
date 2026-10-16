# SPDX-FileCopyrightText: 2026 CircuitPython contributors
# SPDX-License-Identifier: MIT

"""Issue #10871: loop updates, data integrity, lifetime and DMA fallback.

No pins or jumper needed: PIO echoes its OSR internally into its RX FIFO.
Uses only built-in modules and pre-encoded PIO instructions. See README.md.
"""

import array
import gc
import time

import rp2pio

# pull block; mov isr, osr; push block. Backpressure preserves every word,
# including the once buffer, while Python prepares the next capture.
ECHO = array.array("H", [0x80A0, 0xA0C7, 0x8020])
# push noblock allows the exhaustion test to run without an active reader.
ECHO_NOBLOCK = array.array("H", [0x80A0, 0xA0C7, 0x8000])
WORDS = 64


def wait_for(predicate, description):
    deadline = time.monotonic_ns() + 2_000_000_000
    while not predicate():
        assert time.monotonic_ns() < deadline, description


def capture(sm, count):
    received = array.array("I", [0]) * count
    sm.background_read(once=received)
    wait_for(lambda: not sm.reading, "background read timed out")
    return received


def runs(values):
    result = []
    for value in values:
        if result and result[-1][0] == value:
            result[-1][1] += 1
        else:
            result.append([value, 1])
    return result


def stop_and_drain(sm):
    sm.stop_background_write()
    sm.clear_txstall()

    def drained():
        # Let PUSH BLOCK finish so PULL can expose a genuinely empty TX FIFO.
        sm.clear_rxfifo()
        return sm.txstall

    wait_for(drained, "stopped DMA still feeds TX")
    sm.clear_rxfifo()
    # Do not depend on writing=False after stop_background_write().


def check_updates():
    a = array.array("I", [0x12345678]) * WORDS
    b = array.array("I", [0x9ABCDEF0]) * WORDS
    transition = array.array("I", [0x13579BDF]) * WORDS
    for _ in range(4):
        with rp2pio.StateMachine(ECHO, frequency=100_000) as sm:
            sm.background_write(once=a)
            assert capture(sm, WORDS) == a, "one-shot data mismatch"
            wait_for(lambda: not sm.writing, "one-shot write timed out")

            # Restart an exhausted one-shot, then replace a repeating buffer.
            sm.background_write(loop=a)
            assert all(v == a[0] for v in capture(sm, 4 * WORDS))
            sm.background_write(loop=b)
            received = capture(sm, 4 * WORDS)
            assert all(v in (a[0], b[0]) for v in received), "replacement corrupted data"
            assert all(v == b[0] for v in received[-WORDS:]), "replacement never took over"
            sequence = runs(received)
            assert sequence[0] == [a[0], WORDS], "replacement truncated the current buffer"

            sm.background_write(once=transition, loop=b)
            sequence = runs(capture(sm, 4 * WORDS))
            assert sequence == [[b[0], WORDS], [transition[0], WORDS], [b[0], 2 * WORDS]], (
                "once/loop transition lost, truncated or repeated a buffer"
            )

            sm.background_write(once=transition, loop=a, loop2=b)
            sequence = runs(capture(sm, 8 * WORDS))
            assert sequence.pop(0) == [b[0], WORDS], "transition truncated the current buffer"
            assert sequence[0] == [transition[0], WORDS], "once buffer lost or repeated"
            assert len(sequence) >= 5, "alternating loops did not repeat"
            for index, (value, length) in enumerate(sequence[1:]):
                assert value == (a[0] if index % 2 == 0 else b[0]), "wrong loop order"
                if index < len(sequence) - 2:
                    assert length == WORDS, "loop truncated or repeated"
                else:
                    assert 0 < length <= WORDS, "invalid final partial loop"

            # Exercise loop2 alone and transition back from alternating buffers.
            sm.background_write(loop2=transition)
            received = capture(sm, 4 * WORDS)
            assert all(v in (a[0], b[0], transition[0]) for v in received)
            assert all(v == transition[0] for v in received[-WORDS:])
            assert sm.writing
            stop_and_drain(sm)

            # Restart after explicitly stopping DMA and the PIO clock.
            sm.stop()
            sm.restart()
            sm.background_write(loop=b)
            assert all(v == b[0] for v in capture(sm, 4 * WORDS))
            assert sm.writing
            # Context exit deinitializes with an active loop and read channel.
    print("PASS: loop replacement, once/loop/loop2, shared read, stop/restart/deinit")


def check_byteswap():
    for typecode, values, normal, swapped in (
        ("H", (0x1234, 0xABCD), (0x12341234, 0xABCDABCD), (0x34123412, 0xCDABCDAB)),
        ("I", (0x12345678, 0x9ABCDEF0), (0x12345678, 0x9ABCDEF0), (0x78563412, 0xF0DEBC9A)),
    ):
        data = array.array(typecode, values) * (WORDS // 2)
        for swap in (False, True):
            with rp2pio.StateMachine(ECHO, frequency=100_000) as sm:
                sm.background_write(loop=data, swap=swap)
                received = array.array("I", [0]) * (4 * WORDS)
                # Keep RX unswapped, so it cannot undo a broken TX byteswap.
                sm.readinto(received)
                expected = swapped if swap else normal
                assert all(v == expected[i % 2] for i, v in enumerate(received)), "byteswap"
                assert sm.writing
    print("PASS: 16/32-bit loop byteswap")


def check_dma_exhaustion():
    machines = []
    data = array.array("I", [0x12345678]) * WORDS
    try:
        # Completed one-shot writes retain their DMA channel, without needing
        # any repeating-loop acceleration. Reserve reads too, until an actual
        # allocation fails; no chip-specific DMA channel count is assumed.
        while True:
            sm = rp2pio.StateMachine(ECHO_NOBLOCK, frequency=100_000)
            machines.append(sm)
            received = array.array("I", [0]) * WORDS
            try:
                sm.background_read(loop=received)
            except OSError:
                # All channels reserved. Free exactly one for the new writer.
                machines[0].stop_background_read()
                break
            try:
                sm.background_write(once=data)
            except OSError:
                # The read took the last channel; release it for the writer.
                sm.stop_background_read()
                break
            wait_for(lambda: not sm.writing, "reservation one-shot timed out")

        # Only one channel is free. Looping must still work when no optional
        # restart channel can be allocated. Test progress at an IRQ-safe rate,
        # not the high-rate/no-IRQ continuity promise of the companion test.
        sm.background_write(loop=data)
        wait_for(lambda: sm.pending_write == 0, "DMA fallback never started")
        sm.clear_txstall()
        deadline = time.monotonic_ns() + 50_000_000
        while time.monotonic_ns() < deadline:
            assert sm.writing, "fallback loop stopped"
            assert not sm.txstall, "fallback loop made no continuous progress"
        stop_and_drain(sm)
    finally:
        for sm in machines:
            sm.deinit()
    print("PASS: DMA exhaustion fallback and cleanup")


check_updates()
check_byteswap()
gc.collect()
check_dma_exhaustion()
# Recreate and exercise both DMA directions after exhaustion and cleanup.
check_updates()
print("PASS: issue10871 lifecycle")
