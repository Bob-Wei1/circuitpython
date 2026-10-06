# SPDX-FileCopyrightText: 2026 Embedder contributors
# SPDX-License-Identifier: MIT
"""Compile the real backend against fault-injected host boundaries."""

import bisect
import ctypes
import json
import random
import subprocess
import tempfile
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PORT = ROOT / "ports/zephyr-cp"
HAL = PORT / "common-hal/pwmio"

HEADERS = {
    "py/obj.h": "#pragma once\ntypedef struct { const void *type; } mp_obj_base_t;\ntypedef struct { int unused; } mp_obj_type_t;\n",
    "py/runtime.h": "#pragma once\n",
    "common-hal/microcontroller/Pin.h": "#pragma once\n#include <stdint.h>\ntypedef struct { uint16_t package_pin; } mcu_pin_obj_t;\n",
    "shared-bindings/microcontroller/Pin.h": '#pragma once\n#include "common-hal/microcontroller/Pin.h"\n',
    "bindings/zephyr_kernel/__init__.h": "#pragma once\n_Noreturn void raise_zephyr_error(int error);\n",
    "zephyr/device.h": "#pragma once\n#include <stdbool.h>\nstruct device { bool ready; };\nint device_init(const struct device *dev);\nint device_deinit(const struct device *dev);\nbool device_is_ready(const struct device *dev);\n",
    "zephyr/drivers/pwm.h": "#pragma once\n#include <stdint.h>\n#include <zephyr/device.h>\n#define PWM_POLARITY_NORMAL 0U\nint pwm_set_cycles(const struct device *, uint32_t, uint32_t, uint32_t, uint32_t);\nint pwm_get_cycles_per_sec(const struct device *, uint32_t, uint64_t *);\n",
    "iobroker/iobroker.h": "#pragma once\n#include <stdint.h>\n#include <zephyr/device.h>\nint iobroker_pwm_allocate(uint16_t pin, const struct device **dev);\nint iobroker_release_checked(const struct device *dev);\n",
}

HARNESS = r"""
#include <assert.h>
#include <errno.h>
#include <setjmp.h>
#include <stddef.h>
#include <stdio.h>
#include "shared-bindings/pwmio/PWMOut.h"

static struct device dev;
typedef struct { bool in_use; bool routed; uint8_t pin_count; } iobroker_state_t;
static iobroker_state_t claim;
static int fail_allocate, fail_init, fail_clock, fail_set_count, fail_deinit;
static uint64_t clock_hz;
static uint32_t hw_period, hw_pulse, set_calls, boundary_calls;
static jmp_buf exception;
static int last_error;
static unsigned cases;

static bool iobroker_state_find(const struct device *device, iobroker_state_t **out) {
    if (device != &dev) { return false; }
    *out = &claim;
    return true;
}

CHECKED_RELEASE

int device_init(const struct device *device) {
    boundary_calls++;
    assert(device == &dev);
    if (fail_init != 0) { return fail_init; }
    dev.ready = true;
    return 0;
}
int device_deinit(const struct device *device) {
    boundary_calls++;
    assert(device == &dev);
    if (fail_deinit != 0) { return fail_deinit; }
    if (!dev.ready) { return -EPERM; }
    dev.ready = false;
    hw_period = 0;
    hw_pulse = 0;
    return 0;
}
bool device_is_ready(const struct device *device) { return device->ready; }
int iobroker_pwm_allocate(uint16_t pin, const struct device **out) {
    boundary_calls++;
    if (fail_allocate != 0) { return fail_allocate; }
    if (pin == 0) { return -EINVAL; }
    if (claim.in_use) { return -ENODEV; }
    claim = (iobroker_state_t){true, true, 4};
    *out = &dev;
    return 0;
}
int pwm_get_cycles_per_sec(const struct device *device, uint32_t channel, uint64_t *out) {
    boundary_calls++;
    assert(device == &dev && channel == 0);
    if (fail_clock != 0) { return fail_clock; }
    *out = clock_hz;
    return 0;
}
int pwm_set_cycles(const struct device *device, uint32_t channel, uint32_t period,
    uint32_t pulse, uint32_t flags) {
    boundary_calls++;
    assert(device == &dev && dev.ready && channel == 0 && flags == 0);
    assert(period != 0 && pulse <= period);
    set_calls++;
    hw_period = period;
    hw_pulse = pulse;
    if (fail_set_count != 0) { fail_set_count--; return -EIO; }
    return 0;
}
_Noreturn void raise_zephyr_error(int error) { last_error = error; longjmp(exception, 1); }
void common_hal_pwmio_pwmout_raise_error(pwmout_result_t result) {
    assert(result != PWMOUT_OK);
    raise_zephyr_error(-EINVAL);
}
static void reset(void) {
    dev.ready = false;
    claim = (iobroker_state_t){0};
    fail_allocate = fail_init = fail_clock = fail_set_count = fail_deinit = 0;
    clock_hz = PWMIO_NRF_CLOCK_HZ;
    hw_period = hw_pulse = set_calls = boundary_calls = 0;
    last_error = 0;
}
#define EXPECT_ERROR(code, expected) do { \
    if (setjmp(exception) == 0) { code; assert(!"expected exception"); } \
    assert(last_error == (expected)); cases++; \
} while (0)
int main(void) {
    const mcu_pin_obj_t pin = {1};
    pwmio_pwmout_obj_t self;
    #if defined(CONFIG_PM_DEVICE) || defined(CONFIG_PM_DEVICE_RUNTIME)
    const uint32_t frequencies[] = {4, 500, 4000000};
    const uint16_t duties[] = {0, 32768, 65535};
    for (size_t f = 0; f < sizeof(frequencies) / sizeof(frequencies[0]); f++) {
        for (size_t d = 0; d < sizeof(duties) / sizeof(duties[0]); d++) {
            for (unsigned variable = 0; variable < 2; variable++) {
                reset();
                self = (pwmio_pwmout_obj_t){.pin = &pin, .device = &dev,
                    .programmed = true, .pulse_cycles = 123, .duty_cycle = 456};
                assert(common_hal_pwmio_pwmout_construct(&self, &pin, duties[d],
                    frequencies[f], variable != 0) == PWMOUT_INITIALIZATION_ERROR);
                assert(self.pin == NULL && self.device == NULL && !self.programmed);
                assert(self.timing.period_cycles == 0 && self.pulse_cycles == 0);
                assert(self.duty_cycle == 0 && self.variable_frequency == (variable != 0));
                assert(common_hal_pwmio_pwmout_deinited(&self));
                common_hal_pwmio_pwmout_deinit(&self);
                assert(boundary_calls == 0 && !claim.in_use && !dev.ready);
                assert(hw_period == 0 && hw_pulse == 0 && set_calls == 0 && last_error == 0);
                cases++;
            }
        }
    }
    printf("{\"configuration_rejections\":%u,\"hardware_calls\":%u}\n", cases, boundary_calls);
    #else
    const uint32_t invalid[] = {0, 1, 2, 3, 4000001, UINT32_MAX};
    for (size_t i = 0; i < sizeof(invalid) / sizeof(invalid[0]); i++) {
        reset();
        assert(common_hal_pwmio_pwmout_construct(&self, &pin, 0, invalid[i], true) == PWMOUT_INVALID_FREQUENCY);
        assert(!claim.in_use && self.device == NULL); cases++;
    }
    const int allocation_errors[] = {-EINVAL, -EBUSY, -ENODEV, -ENOSYS, -EIO};
    const pwmout_result_t outcomes[] = {PWMOUT_INVALID_PIN, PWMOUT_INTERNAL_RESOURCES_IN_USE,
        PWMOUT_INTERNAL_RESOURCES_IN_USE, PWMOUT_INITIALIZATION_ERROR, PWMOUT_INITIALIZATION_ERROR};
    for (size_t i = 0; i < 5; i++) {
        reset(); fail_allocate = allocation_errors[i];
        assert(common_hal_pwmio_pwmout_construct(&self, &pin, 0, 500, true) == outcomes[i]);
        assert(!claim.in_use && self.device == NULL); cases++;
    }
    for (unsigned stage = 0; stage < 4; stage++) {
        reset();
        if (stage == 0) { fail_init = -EIO; }
        if (stage == 1) { fail_clock = -EIO; }
        if (stage == 2) { clock_hz = 8000000; }
        if (stage == 3) { fail_set_count = 1; }
        assert(common_hal_pwmio_pwmout_construct(&self, &pin, 0, 500, true) == PWMOUT_INITIALIZATION_ERROR);
        assert(!claim.in_use && self.device == NULL && !dev.ready); cases++;
    }
    reset(); fail_clock = -EIO; fail_deinit = -EIO;
    assert(common_hal_pwmio_pwmout_construct(&self, &pin, 0, 500, true) == PWMOUT_INITIALIZATION_ERROR);
    assert(claim.in_use && self.device != NULL);
    fail_deinit = 0; common_hal_pwmio_pwmout_deinit(&self);
    assert(!claim.in_use && self.device == NULL); cases++;

    reset();
    assert(common_hal_pwmio_pwmout_construct(&self, &pin, 32768, 500, true) == PWMOUT_OK);
    assert(common_hal_pwmio_pwmout_get_frequency(&self) == 500);
    assert(hw_period == 32000 && hw_pulse == 16000);
    common_hal_pwmio_pwmout_set_duty_cycle(&self, 32768);
    assert(set_calls == 1);
    common_hal_pwmio_pwmout_set_duty_cycle(&self, 0);
    assert(hw_pulse == 0);
    common_hal_pwmio_pwmout_set_duty_cycle(&self, 65535);
    assert(hw_pulse == hw_period); cases++;

    common_hal_pwmio_pwmout_set_duty_cycle(&self, 16384);
    const uint32_t previous_period = hw_period, previous_pulse = hw_pulse;
    fail_set_count = 1;
    EXPECT_ERROR(common_hal_pwmio_pwmout_set_frequency(&self, 1000), -EIO);
    assert(hw_period == previous_period && hw_pulse == previous_pulse);
    assert(common_hal_pwmio_pwmout_get_frequency(&self) == 500);
    fail_set_count = 2;
    EXPECT_ERROR(common_hal_pwmio_pwmout_set_frequency(&self, 1000), -EIO);
    EXPECT_ERROR((void)common_hal_pwmio_pwmout_get_frequency(&self), -EIO);
    EXPECT_ERROR((void)common_hal_pwmio_pwmout_get_duty_cycle(&self), -EIO);
    common_hal_pwmio_pwmout_set_frequency(&self, 1000);
    assert(self.programmed && hw_period == 16000 && hw_pulse == 4000); cases++;

    fail_deinit = -EBUSY;
    EXPECT_ERROR(common_hal_pwmio_pwmout_deinit(&self), -EBUSY);
    assert(claim.in_use && self.device == &dev && dev.ready);
    fail_deinit = 0;
    common_hal_pwmio_pwmout_deinit(&self);
    common_hal_pwmio_pwmout_deinit(&self);
    assert(common_hal_pwmio_pwmout_deinited(&self) && !claim.in_use); cases++;
    assert(iobroker_release_checked(NULL) == -EINVAL); cases++;
    for (unsigned cycle = 0; cycle < 100; cycle++) {
        assert(common_hal_pwmio_pwmout_construct(&self, &pin, 1, 4, false) == PWMOUT_OK);
        common_hal_pwmio_pwmout_deinit(&self);
        assert(!claim.in_use && !dev.ready); cases++;
    }
    printf("{\"lifecycle_cases\":%u,\"pm_build\":false}\n", cases);
    #endif
}
"""


def release_function():
    text = (PORT / "internal-modules/iobroker/src/nordic/nrf/iobroker_route.c").read_text()
    start = text.index("int iobroker_release_checked(")
    end = text.index("\nbool iobroker_release(", start)
    return text[start:end]


class Timing(ctypes.Structure):
    _fields_ = [
        ("period", ctypes.c_uint32),
        ("frequency", ctypes.c_uint32),
        ("top", ctypes.c_uint16),
        ("prescaler", ctypes.c_uint8),
    ]


def main():
    report = {}
    with tempfile.TemporaryDirectory(prefix="pwm-host-") as directory:
        temp = Path(directory)
        for name, contents in HEADERS.items():
            path = temp / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(contents)
        flags = [
            "clang",
            "-std=c11",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-O2",
            "-I",
            str(temp),
            "-I",
            str(PORT),
            "-I",
            str(ROOT),
        ]
        harness = temp / "test.c"
        harness.write_text(HARNESS.replace("CHECKED_RELEASE", release_function()))
        configurations = (
            ("no_pm", []),
            ("pm", ["-DCONFIG_PM_DEVICE=1"]),
            ("runtime_pm", ["-DCONFIG_PM_DEVICE_RUNTIME=1"]),
            ("pm_and_runtime_pm", ["-DCONFIG_PM_DEVICE=1", "-DCONFIG_PM_DEVICE_RUNTIME=1"]),
        )
        for name, defines in configurations:
            executable = temp / name
            subprocess.run(
                flags
                + defines
                + [
                    "-fsanitize=address,undefined",
                    str(harness),
                    str(HAL / "PWMOut.c"),
                    str(HAL / "pwm_timing.c"),
                    "-o",
                    str(executable),
                ],
                check=True,
            )
            report[name] = json.loads(subprocess.check_output([str(executable)], text=True))
        library = temp / "timing.dylib"
        subprocess.run(
            flags + ["-shared", "-fPIC", str(HAL / "pwm_timing.c"), "-o", str(library)], check=True
        )
        dll = ctypes.CDLL(str(library))
        dll.pwmio_compute_timing.argtypes = [ctypes.c_uint32, ctypes.POINTER(Timing)]
        dll.pwmio_compute_timing.restype = ctypes.c_bool
        dll.pwmio_compute_pulse.argtypes = [ctypes.POINTER(Timing), ctypes.c_uint16]
        dll.pwmio_compute_pulse.restype = ctypes.c_uint32
        periods = sorted({top * (1 << p) for p in range(8) for top in range(4, 32768)})
        rng = random.Random(54)
        frequencies = {4, 5, 50, 500, 1000, 4000000, 3999999}
        frequencies.update(rng.randrange(4, 4000001) for _ in range(3000))
        for p in range(8):
            for top in (4, 5, 16383, 16384, 32766, 32767):
                boundary = 16000000 // (top * (1 << p))
                frequencies.update(
                    f for f in range(boundary - 2, boundary + 3) if 4 <= f <= 4000000
                )
        for frequency in frequencies:
            timing = Timing()
            assert dll.pwmio_compute_timing(frequency, ctypes.byref(timing))
            position = bisect.bisect_left(periods, Fraction(16000000, frequency))
            neighbors = periods[max(0, position - 1) : position + 1]
            expected_error = min(
                abs(Fraction(16000000, period) - frequency) for period in neighbors
            )
            assert abs(Fraction(16000000, timing.period) - frequency) == expected_error
            top = timing.period
            shift = 0
            while top > 32767:
                top >>= 1
                shift += 1
            assert (top, shift) == (timing.top, timing.prescaler)
            assert timing.frequency == (16000000 + timing.period // 2) // timing.period
        for frequency in (0, 1, 2, 3, 4000001, 0xFFFFFFFF):
            timing = Timing(123, 456, 7, 2)
            assert not dll.pwmio_compute_timing(frequency, ctypes.byref(timing))
            assert timing.period == 123 and timing.frequency == 456
        assert not dll.pwmio_compute_timing(500, None)
        duty_checks = 0
        for top, shift in ((4, 0), (5, 0), (32000, 0), (20000, 4), (32767, 7)):
            timing = Timing(top << shift, 0, top, shift)
            previous = 0
            for duty in range(65536):
                pulse = dll.pwmio_compute_pulse(ctypes.byref(timing), duty)
                assert pulse == ((duty * top + 32767) // 65535) << shift
                assert previous <= pulse <= timing.period
                previous = pulse
                duty_checks += 1
            assert previous == timing.period
        report["frequency_oracle_cases"] = len(frequencies)
        report["exhaustive_duty_cases"] = duty_checks
    destination = Path(__file__).with_name("results")
    destination.mkdir(exist_ok=True)
    (destination / "host.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
