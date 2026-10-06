# nRF54 CircuitPython PWM example

Extends the existing Zephyr port with `pwmio.PWMOut`; this is not a new nRF54 board port.

## Reproduce

- CircuitPython base: `7d715c1a20afde2dc4995d966c54cf2d6507230f`.
- Zephyr: manifest-pinned `a4d81519a1affe11254b049ba565f124fa53671d`.
- Zephyr SDK used: 1.0.1, ARM GCC 14.3.0.
- Physical board: nRF54LM20 DK / LM20B. Build alias `nordic_nrf54lm20dk`
  selects the upstream LM20A compatibility configuration (`DEVELOP_IN_NRF54LM20B=y`).

From `ports/zephyr-cp`, initialize the port's west manifest and submodules per its README,
then run `make BOARD=nordic_nrf54lm20dk`. Keep both debugger and MCU USB connected.
Flash through the configured J-Link runner; the MCU USB exposes CIRCUITPY and the REPL.
Do not mass-erase or replace an existing filesystem without a backup.

From the repository root, run `python examples/nrf54_pwm/test_host.py` (Clang required).
Copy `target_tests.py` to CIRCUITPY, enter the REPL, and run
`exec(open('target_tests.py').read())`. Assertions and JSON show failures explicitly.
Copy `led_fade.py` or `servo_pulses.py` as `code.py` for a demo; install the unchanged
Adafruit Motor package for the latter. Verify servo voltage, power and limits before attachment.

## Wiring

AD3 scope `1+` -> DK **PORT3 pin 04 / P3.04**; scope `1−` and AD3 GND -> DK GND.
Leave AD3 supply/wavegen/digital-output leads disconnected. Verify actual IO voltage;
the DK's default is 1.8 V, not an assumed 3.3 V. Use analog capture before digital logic.

## Observed results

- Host: 3,122 independent frequency-oracle checks; 327,680 duty checks;
  250 sanitized lifecycle/fault-injection cases.
- Existing Zephyr tooling suite: 59 passed. LM20 build passed; unsupported RP2040
  build passed with pwmio disabled. Full Linux native_sim suite was not run (Docker daemon stopped).
- Physical target: all 8 API/lifecycle groups passed, including 100 construct/deinit cycles
  and 20 soft reloads with a live PWM object. Original `code.py` was restored.
- AD3: **41 of 42 matrix points passed**, no lost/corrupted samples. The 4 MHz point's
  frequency check passed, but narrow-pulse duty accuracy is **inconclusive** with the AD3 MTE bandwidth.
- 500 Hz / 50%: approximately **500.00 Hz**, **50.00%**, **1.000 ms high**, **2.000 ms period**.
- Unmodified Adafruit servo library: measured **1.000 / 1.500 / 2.000 ms** pulses at 50 Hz.
  No physical motor movement is claimed.
- Software setter timing: repeated writes averaged about 6.8 us; alternating writes about 13.8 us.
  These are not a controlled uncached-baseline speedup or a comparison with another coding agent.

See `results/host.json`, `target.json`, `target-serial.log`, `ad3-500hz.json`, and
`ad3-matrix.json`. Raw CSVs are retained locally but ignored by Git. The matrix uses
an explicit 0.5% functional frequency gate; absolute clock/timebase accuracy remains unqualified.
Edge interpolation does not turn the sample interval into a calibrated jitter measurement.

## Limits

One whole PWM controller per output; two dynamically routable controllers on this DK.
GPIO P1/P3 domain restrictions apply; NeoPixel transmission competes for those controllers.
Supported request range is conservatively 4 Hz–4 MHz (TOP >= 4). LM20B headers permit TOP 3,
but it has not been qualified here. No new polarity, center-alignment, ISR or channel-sharing API.

Full MISRA C:2025 compliance is **not claimed**; see `COMPLIANCE.md` and `results/analysis.json`.
Second-channel electrical independence, load/NeoPixel concurrency, and calibrated high-frequency
pulse-width checks remain separate verification work.
