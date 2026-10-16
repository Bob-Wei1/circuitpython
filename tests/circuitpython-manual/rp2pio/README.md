# rp2pio manual tests

## Audio DMA shared IRQs

These programs exercise the `DMA_IRQ_0` interrupt handlers on the RP2040 /
RP2350, which are shared between `audiocore`/`audiopwmio` (audio DMA) and
`rp2pio` (PIO background read/write DMA).

They were written to validate the change in issue #9992 (moving `audio_dma.c`
off the fixed `isr_dma_0()` linker symbol and onto `irq_add_shared_handler()`,
with `rp2pio` registering its own shared handler). **They use only public APIs
that predate that change, so each program should behave identically before and
after it** — that is the point: they are regression tests, not feature tests.

## What each program covers

| Program | Audio DMA | PIO write DMA | PIO read DMA |
|---|---|---|---|
| `pio_background_write.py`        |     | ✓ |   |
| `audio_dma_shared_irq_write.py`  | ✓   | ✓ |   |
| `audio_dma_shared_irq_loopback.py` | ✓ | ✓ | ✓ |

Each goes through the background-DMA path (`background_write` /
`background_read`), which is interrupt-driven. The blocking `write`/`readinto`/
`write_readinto` calls poll instead and do **not** use the DMA IRQ, so they are
deliberately not used here. The audio sample is created with
`single_buffer=False` so audio also uses the interrupt-driven (double-buffered)
DMA path rather than the no-interrupt single-buffer chaining path.

## Wiring (Raspberry Pi Pico / Pico 2)

- `GP13` — PWM audio output. Connect to an amplifier/speaker, or just leave it;
  the test does not require you to hear anything, only that playback keeps
  running.
- `GP2`  — PIO output pin.
- `GP3`  — PIO input pin (loopback test only). For a meaningful loopback,
  connect `GP2` to `GP3` with a jumper. Without the jumper the read still
  completes (it just reads whatever the floating/pulled pin sees), so the DMA
  path is still exercised.

## Running

Copy one file at a time to `CIRCUITPY/code.py` and watch the serial console.
A successful run ends with a `PASS:` line. A hang (no further output) or a
`RuntimeError`/crash/safe-mode indicates a regression in the shared DMA IRQ
handling.

## Issue #10871: continuous background-write loops

These two standalone tests need only built-in modules, no assembler, wiring,
external libraries, or particular board pin names. They do not drive any pins.
Run on an otherwise idle RP2350 board with enough free RAM for a 168000-byte
buffer, at the normal CPU frequency. Stop other code using DMA/PIO first. Copy
one script at a time to `CIRCUITPY/code.py`, or copy it under its original name
and run, for example, `exec(open("issue10871_continuity.py").read())` at the REPL.
Run both scripts on the baseline and the patched firmware.

- `issue10871_continuity.py` loops a non-power-of-two **168000-byte** buffer at
  **25 MHz**, separately with 8-, 16-, and 32-bit DMA elements. It clears the
  initial TX stall, then checks both `writing` and the sticky `txstall` flag
  during 100 ms of steady-state transmission. A separate **20 ms IRQ blackout**
  uses `time.monotonic_ns()` and a `finally` block to restore interrupts. Even
  the longest loop period is only 13.44 ms, so every blackout crosses a buffer
  completion. CPU-interrupt-driven restarts should fail a continuity assertion
  (normally the steady-state check; otherwise the blackout check). The hardware
  restart fix should pass both. Only identical repeated buffers are required
  to be continuous; alternating and one-shot transfers are tested separately.
- `issue10871_lifecycle.py` checks full data using internal PIO loopback. It
  verifies one-shot completion, loop replacement, a once-only transition into
  alternating `loop`/`loop2` buffers, `loop2` alone, stop/restart/deinit,
  background-read completion on the same state machine, and 16-/32-bit byte
  swapping. Blocking RX backpressure preserves complete buffers for these
  content tests; they deliberately do not assert high-rate continuity.
  It then reserves DMA channels with reads and completed one-shot writes until
  allocation actually fails, releases one channel, and verifies that a loop
  still progresses using the resource-constrained fallback. Resources are
  released in `finally`, and the lifecycle checks run again after cleanup.
  This script should pass both the baseline and the fix.

Expected output with the fix:

```text
PASS: continuous 8 bit, 168000 bytes, 25MHz, IRQ blackout
PASS: continuous 16 bit, 168000 bytes, 25MHz, IRQ blackout
PASS: continuous 32 bit, 168000 bytes, 25MHz, IRQ blackout
PASS: issue10871 continuity
```

```text
PASS: loop replacement, once/loop/loop2, shared read, stop/restart/deinit
PASS: 16/32-bit loop byteswap
PASS: DMA exhaustion fallback and cleanup
PASS: loop replacement, once/loop/loop2, shared read, stop/restart/deinit
PASS: issue10871 lifecycle
```

An assertion, exception, hang, crash, or safe-mode reset is a failure. The tests
verify stopping by observing FIFO starvation after draining queued data; they
intentionally do **not** require `writing == False` after
`stop_background_write()`. The continuity script is the baseline/fix
regression discriminator; neither script inspects DMA registers or assumes
which channel implements a transfer.
