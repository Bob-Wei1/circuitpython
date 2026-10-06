# Scoped MISRA evidence — incomplete

Target: **MISRA C:2025**, newly authored PWM C code and checked-release additions.
Adopted CircuitPython/Zephyr/Nordic code and generated headers are not claimed compliant.
The user elected to run available checks without supplying the licensed C:2025 reference.
**No full compliance claim or approved deviation is recorded.**

| Obligation | Current evidence / gap |
|---|---|
| Arithmetic bounds | Host oracle, exhaustive duty sweeps, ASan/UBSan. Products/rounding fit unsigned 32 bits; frequency-error comparisons use bounded unsigned 64 bits. |
| Lifetime/error handling | Fault-injected allocation/init/clock/set/cleanup tests; physical claim, GC, context-exit, 100-cycle and 20-reload tests. Failed checked teardown preserves the claim. |
| Target context | Actual ARM GCC compiler arguments captured, not a Zephyr-only CMake database. SDK headers confirm TOP max 32767, prescaler 0–7 and 16 MHz clock. |
| Automated coverage | Cppcheck 2.21.0 MISRA C:2012 addon is partial coverage, not C:2025 enforcement. Logs/checker manifests retained locally. |
| Parsing limitations | Original target scan stops at an adopted MP_INT_MAX preprocessor directive. Compiler-preprocessed scan reaches adopted ARM switch/assembly syntax unsupported by the checker. Backend analysis is therefore incomplete. |
| Reported findings | Preprocessed bool constants, generated line directives and exported helpers generate 10.3/20.13/8.7 findings. Macro provenance and missing caller coverage must be reviewed, not silently suppressed. |
| Framework boundaries | Object/layout macros, nonlocal Python exceptions, exported HAL callbacks and inherited driver waits require licensed-rule/manual review and location-specific deviation decisions. |
| Remaining checks | Full C:2025 enforcement plan, uncovered directives/system-wide analysis, reviewed broker additions, and user-approved required deviations if unavoidable. |

`results/analysis.json` records tool scope and nonzero analysis status. A successful build,
clean subset, or hardware test does **not** establish MISRA compliance. No check was disabled
to obtain a passing compliance result. Implementation review was performed by the main agent
as requested; it is not represented as an independent post-implementation review.
