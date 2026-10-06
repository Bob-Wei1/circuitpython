# SPDX-FileCopyrightText: 2026 Embedder contributors
# SPDX-License-Identifier: MIT
"""Runnable CircuitPython API/lifecycle tests; electrical tests are separate."""

import gc
import json
import time

import board
import digitalio
import pwmio


def main():
    results = []

    def check(name, operation):
        try:
            operation()
            results.append({"id": name, "status": "pass"})
        except (
            AssertionError,
            RuntimeError,
            ValueError,
            TypeError,
            OSError,
            AttributeError,
            ArithmeticError,
            MemoryError,
        ) as error:
            results.append({"id": name, "status": "fail", "error": repr(error)})
        gc.collect()

    def rejected(operation, kinds):
        try:
            operation()
        except kinds:
            return
        raise AssertionError("Expected rejection")

    def invalid_frequency():
        for frequency in (0, -1, 1, 3, 4000001, 2**40, "bad"):
            rejected(
                lambda frequency=frequency: pwmio.PWMOut(board.PORT3_04, frequency=frequency),
                (ValueError, OverflowError, TypeError),
            )
        with pwmio.PWMOut(board.PORT3_04) as output:
            assert output.frequency == 500

    def endpoints():
        with pwmio.PWMOut(board.PORT3_04, variable_frequency=True) as output:
            for frequency in (4, 5, 50, 488, 489, 500, 1000, 1234, 4000000):
                output.frequency = frequency
                for duty in (0, 1, 2, 16384, 32768, 49151, 65533, 65534, 65535):
                    output.duty_cycle = duty
                    assert output.duty_cycle == duty
                assert output.frequency > 0
            for bad in (-1, 65536, "bad"):
                rejected(
                    lambda bad=bad: setattr(output, "duty_cycle", bad), (ValueError, TypeError)
                )
            old = output.frequency
            rejected(lambda: setattr(output, "frequency", 0), ValueError)
            assert output.frequency == old

    def fixed_and_deinit():
        output = pwmio.PWMOut(board.PORT3_04)
        rejected(lambda: setattr(output, "frequency", 1000), AttributeError)
        output.deinit()
        output.deinit()
        rejected(lambda: output.frequency, ValueError)
        with pwmio.PWMOut(board.PORT3_04):
            pass

    def claims():
        with digitalio.DigitalInOut(board.PORT3_04):
            rejected(lambda: pwmio.PWMOut(board.PORT3_04), (ValueError, RuntimeError))
        with pwmio.PWMOut(board.PORT3_04):
            rejected(lambda: digitalio.DigitalInOut(board.PORT3_04), (ValueError, RuntimeError))
            with pwmio.PWMOut(board.PORT3_05, frequency=1000):
                rejected(lambda: pwmio.PWMOut(board.PORT3_06), RuntimeError)
        with pwmio.PWMOut(board.PORT3_06):
            pass
        rejected(lambda: pwmio.PWMOut(board.PORT0_00), ValueError)

    def context_failure():
        try:
            with pwmio.PWMOut(board.PORT3_04):
                raise ValueError("test")
        except ValueError:
            pass
        with pwmio.PWMOut(board.PORT3_04):
            pass

    def cycles():
        for _ in range(100):
            with pwmio.PWMOut(board.PORT3_04, frequency=50) as output:
                output.duty_cycle = 32768

    def collected():
        output = pwmio.PWMOut(board.PORT3_04)
        del output
        gc.collect()
        with pwmio.PWMOut(board.PORT3_04):
            pass

    def update_cost():
        with pwmio.PWMOut(board.PORT3_04, frequency=1000) as output:
            start = time.monotonic_ns()
            for _ in range(1000):
                output.duty_cycle = 32768
            repeated_ns = time.monotonic_ns() - start
            start = time.monotonic_ns()
            for index in range(1000):
                output.duty_cycle = 32768 + (index % 2) * 1000
            changed_ns = time.monotonic_ns() - start
            print(
                "PWM_BENCH "
                + json.dumps(
                    {"updates": 1000, "repeated_ns": repeated_ns, "changed_ns": changed_ns}
                )
            )

    for name, operation in (
        ("invalid_frequency", invalid_frequency),
        ("endpoints", endpoints),
        ("fixed_deinit", fixed_and_deinit),
        ("claims", claims),
        ("context_exception", context_failure),
        ("cycles_100", cycles),
        ("garbage_collection", collected),
        ("update_cost", update_cost),
    ):
        check(name, operation)
    print("PWM_RESULTS " + json.dumps(results))
    assert all(result["status"] == "pass" for result in results)


if __name__ == "__main__":
    main()
