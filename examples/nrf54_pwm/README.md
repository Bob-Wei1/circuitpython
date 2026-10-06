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
do not assume 3.3 V from the board name. This setup measured approximately 3 V high,
which does not establish its rail configuration or validate a nominal/default 1.8 V setting.
Use analog capture before digital logic.

For the Siglent SDS812X HD tests: CH1 tip -> **P3.04**, CH2 tip -> **P3.05**,
both grounds -> DK GND. Use compensated ×10 probes with matching channel attenuation,
DC coupling and 1 MΩ inputs. Disconnect AD3 signal leads. Never put a probe ground on a signal.

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

## Siglent follow-up measurements

Same firmware, tested on 2026-10-06 with an SDS812X HD, firmware 3.8.12.1.1.6.5.
`results/siglent.json` records **25 valid captures**, **21 passed functional channel checks**
with zero channel-check failures, and **14 transition observations**. Transition records
are characterization, not a guarantee of glitch-free or immediate setters.

At an actual **1 GSa/s**, 1 us/div and 10,000 samples per channel:

| Requested duty at 4 MHz | Quantized high time | Measured high time | Measured duty |
|---|---|---|---|
| 16384 | 62.5 ns | 59.704 ns | 23.882% |
| 32768 | 125 ns | 122.133 ns | 48.854% |
| 49152 | 187.5 ns | 184.576 ns | 73.834% |

These passed a predeclared **±5 ns functional pulse-width gate** and a 0.5% frequency gate.
The pulse gate is `max(5 ns, two actual sample intervals, 0.005 * expected period)`;
the shortest pulse must span at least 20 samples, and 40%/60% threshold checks must stay
within the pulse gate of the 50% result. At 4 MHz, ±5 ns allows ±2 percentage points of duty:
it is **not** 0.5% duty precision or a traceable calibration uncertainty budget.
The original AD3 point remains inconclusive; these are separate higher-bandwidth results.

- Simultaneous 4 MHz / 2 MHz outputs and independent changes at 1234 / 1000 / 700 Hz
  passed on P3.04/P3.05.
- USB/allocation/GC, BLE advertising plus USB/GC, and NeoPixel plus USB/GC each ran
  for approximately 6 seconds. The accepted **0.2-second** records at 500 kSa/s had no
  complete PWM periods or high pulses outside their declared gates. These are bounded
  snapshots, not continuous six-second or endurance qualification. BLE advertising was
  also observed over air; connected BLE traffic was not tested.
- With one PWM active, **1,537 NeoPixel write calls** used the other controller; CH2
  showed transmission activity, and subsequent two-PWM allocation/waveforms passed.
  No physical LED color, NeoPixel bit timing, or forced controller-exhaustion result is claimed.
- Selected 1 kHz duty and 1 -> 2 kHz frequency transitions showed the expected endpoint
  pulse widths/periods, without an anomalous complete pulse in those records.
- At **4 Hz / 50%**, stopping about 1 ms after a rising edge left the pin high for
  **123.87–123.91 ms** after the setter marker. An immediate stop/restart at that phase
  blocked the restart setter for **248.90–248.93 ms** by the quantized target timer;
  the enclosing GPIO markers measured **248.94–248.96 ms** at 100 kSa/s (10 us/sample).
  Zephyr's nRF PWM driver stops at the current period's end and waits for a pending stop
  before restarting. Setter return and physical output change are different events.
  These are three near-start trials, not phase-exhaustive calibrated worst-case bounds.

Raw CSVs, screenshots and full instrument/serial records are retained locally in
`.embedder/hardware/cases/pwm-siglent-verification`; the public JSON includes raw-file
SHA-256 digests, actual acquisition settings and gates, but omits hardware serial numbers,
network addresses, private capture identifiers and machine-specific paths. Early loose-CH2
and not-yet-Ready marker attempts were excluded and rerun after correcting the setup.
Both PWM objects were deinitialized, BLE was restored off, and `code.py` was unchanged.
The temporary `pwm_scope_probe.py` remains on CIRCUITPY because outside-workspace deletion
was denied; it does not run automatically as `code.py`.

## Limits

One whole PWM controller per output; two dynamically routable controllers on this DK.
GPIO P1/P3 domain restrictions apply; NeoPixel transmission competes for those controllers.
Supported request range is conservatively 4 Hz–4 MHz (TOP >= 4). LM20B headers permit TOP 3,
but it has not been qualified here. No new polarity, center-alignment, ISR or channel-sharing API.

Full MISRA C:2025 compliance is **not claimed**; see `COMPLIANCE.md` and `results/analysis.json`.
Traceably calibrated high-frequency pulse-width/absolute jitter checks, connected BLE and
longer load/exhaustion coverage remain open. PM hardware cases were not run with PM disabled.
Low-frequency stop/restart can delay physical output changes and block the VM for nearly
one period; do not infer a universal microsecond setter bound from the cached-write benchmark.
