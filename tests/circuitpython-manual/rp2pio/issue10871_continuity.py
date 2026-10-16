# SPDX-FileCopyrightText: 2026 CircuitPython contributors
# SPDX-License-Identifier: MIT

"""Issue #10871: arbitrary-length background_write loops must not starve TX.

Run on an otherwise idle RP2350 at its normal CPU frequency. No pins, jumper,
external libraries, or assembler are needed. See README.md for expected output.
"""

import array
import gc
import time

import microcontroller
import rp2pio

# out null, 8 [1]: consume one FIFO entry every two PIO clocks. The narrow
# DMA writes replicate their value, but only eight bits of each entry are used.
PROGRAM = array.array("H", [0x6168])
BUFFER_BYTES = 168000  # Deliberately not a power of two / DMA ring size.
BLACKOUT_NS = 20_000_000


def check_continuity(typecode, element_bytes):
    data = array.array(typecode, [0x35]) * (BUFFER_BYTES // element_bytes)
    with rp2pio.StateMachine(
        PROGRAM, frequency=25_000_000, auto_pull=True, pull_threshold=8
    ) as sm:
        sm.background_write(loop=data)
        deadline = time.monotonic_ns() + 2_000_000_000
        while sm.pending_write:
            assert time.monotonic_ns() < deadline, "loop never started"
        # Exclude the unavoidable initial empty FIFO and first completion.
        time.sleep(0.02)
        sm.clear_txstall()
        deadline = time.monotonic_ns() + 100_000_000
        while time.monotonic_ns() < deadline:
            assert sm.writing, "loop stopped unexpectedly"
            assert not sm.txstall, "TX FIFO starved at a DMA loop boundary"

        # The longest period is 168000 * 2 / 25MHz = 13.44 ms (8-bit).
        # 20 ms must cross a completion for all three element sizes, regardless
        # of phase. RP2 monotonic_ns reads a hardware timer even with IRQs off.
        sm.clear_txstall()
        microcontroller.disable_interrupts()
        try:
            deadline = time.monotonic_ns() + BLACKOUT_NS
            while time.monotonic_ns() < deadline:
                pass
            stalled = sm.txstall
        finally:
            microcontroller.enable_interrupts()
        assert sm.writing, "loop stopped during IRQ blackout"
        assert not stalled, "DMA loop depends on CPU interrupt service"

        sm.stop_background_write()
        sm.clear_txstall()
        deadline = time.monotonic_ns() + 2_000_000_000
        while not sm.txstall:
            assert time.monotonic_ns() < deadline, "stopped DMA still feeds TX"
        # Do not assert writing=False here: historical stop semantics differ.
    print("PASS: continuous", element_bytes * 8, "bit, 168000 bytes, 25MHz, IRQ blackout")


for typecode, element_bytes in (("B", 1), ("H", 2), ("I", 4)):
    gc.collect()
    check_continuity(typecode, element_bytes)
print("PASS: issue10871 continuity")
