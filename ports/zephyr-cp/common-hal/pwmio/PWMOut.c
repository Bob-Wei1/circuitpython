// SPDX-FileCopyrightText: 2026 Embedder contributors
// SPDX-License-Identifier: MIT
#include "shared-bindings/pwmio/PWMOut.h"
#include "bindings/zephyr_kernel/__init__.h"
#include "py/runtime.h"
#include <errno.h>
#include <stddef.h>
#include <iobroker/iobroker.h>
#include <zephyr/drivers/pwm.h>

static int program_output(pwmio_pwmout_obj_t *self, const pwmio_timing_t *timing,
    uint32_t pulse) {
    int result = 0;
    #if !defined(CONFIG_PM_DEVICE)
    if (self->programmed && (self->timing.period_cycles == timing->period_cycles) &&
        (self->pulse_cycles == pulse)) {
        return result;
    }
    #endif
    result = pwm_set_cycles(self->device, 0U, timing->period_cycles, pulse, PWM_POLARITY_NORMAL);
    if (result != 0) {
        // A failed update may have changed hardware before returning an error.
        if (self->programmed) {
            self->programmed = pwm_set_cycles(self->device, 0U,
                self->timing.period_cycles, self->pulse_cycles, PWM_POLARITY_NORMAL) == 0;
        }
    }
    return result;
}

pwmout_result_t common_hal_pwmio_pwmout_construct(pwmio_pwmout_obj_t *self,
    const mcu_pin_obj_t *pin, uint16_t duty, uint32_t frequency, bool variable_frequency) {
    pwmout_result_t result = PWMOUT_OK;
    pwmio_timing_t timing = {0};
    uint64_t clock = UINT64_C(0);
    self->pin = NULL;
    self->device = NULL;
    self->timing = timing;
    self->pulse_cycles = 0U;
    self->duty_cycle = 0U;
    self->variable_frequency = variable_frequency;
    self->programmed = false;

    if (!pwmio_compute_timing(frequency, &timing)) {
        result = PWMOUT_INVALID_FREQUENCY;
    } else {
        int error = iobroker_pwm_allocate(pin->package_pin, &self->device);
        if (error == -EINVAL) {
            result = PWMOUT_INVALID_PIN;
        } else if ((error == -EBUSY) || (error == -ENODEV)) {
            result = PWMOUT_INTERNAL_RESOURCES_IN_USE;
        } else if (error != 0) {
            result = PWMOUT_INITIALIZATION_ERROR;
        } else {
            self->pin = pin;
            error = device_init(self->device);
            if (error == 0) {
                error = pwm_get_cycles_per_sec(self->device, 0U, &clock);
            }
            if ((error == 0) && (clock != (uint64_t)PWMIO_NRF_CLOCK_HZ)) {
                error = -ENOTSUP;
            }
            const uint32_t pulse = pwmio_compute_pulse(&timing, duty);
            if (error == 0) {
                error = program_output(self, &timing, pulse);
            }
            if (error == 0) {
                self->timing = timing;
                self->pulse_cycles = pulse;
                self->duty_cycle = duty;
                self->programmed = true;
            } else {
                const int cleanup = iobroker_release_checked(self->device);
                if (cleanup == 0) {
                    self->device = NULL;
                    self->pin = NULL;
                }
                // If teardown failed, the finalizer retains a handle to the claimed device.
                result = PWMOUT_INITIALIZATION_ERROR;
            }
        }
    }
    return result;
}

bool common_hal_pwmio_pwmout_deinited(pwmio_pwmout_obj_t *self) {
    return self->device == NULL;
}

void common_hal_pwmio_pwmout_deinit(pwmio_pwmout_obj_t *self) {
    if (self->device != NULL) {
        const int error = iobroker_release_checked(self->device);
        if (error != 0) {
            raise_zephyr_error(error);
        }
        self->device = NULL;
        self->pin = NULL;
        self->programmed = false;
    }
}

void common_hal_pwmio_pwmout_set_duty_cycle(pwmio_pwmout_obj_t *self, uint16_t duty) {
    const uint32_t pulse = pwmio_compute_pulse(&self->timing, duty);
    const int error = program_output(self, &self->timing, pulse);
    if (error != 0) {
        raise_zephyr_error(error);
    }
    self->pulse_cycles = pulse;
    self->duty_cycle = duty;
    self->programmed = true;
}

uint16_t common_hal_pwmio_pwmout_get_duty_cycle(pwmio_pwmout_obj_t *self) {
    if (!self->programmed) {
        raise_zephyr_error(-EIO);
    }
    return self->duty_cycle;
}

void common_hal_pwmio_pwmout_set_frequency(pwmio_pwmout_obj_t *self, uint32_t frequency) {
    pwmio_timing_t timing = {0};
    if (!pwmio_compute_timing(frequency, &timing)) {
        common_hal_pwmio_pwmout_raise_error(PWMOUT_INVALID_FREQUENCY);
    }
    const uint32_t pulse = pwmio_compute_pulse(&timing, self->duty_cycle);
    const int error = program_output(self, &timing, pulse);
    if (error != 0) {
        raise_zephyr_error(error);
    }
    self->timing = timing;
    self->pulse_cycles = pulse;
    self->programmed = true;
}

uint32_t common_hal_pwmio_pwmout_get_frequency(pwmio_pwmout_obj_t *self) {
    if (!self->programmed) {
        raise_zephyr_error(-EIO);
    }
    return self->timing.frequency;
}

bool common_hal_pwmio_pwmout_get_variable_frequency(pwmio_pwmout_obj_t *self) {
    return self->variable_frequency;
}

const mcu_pin_obj_t *common_hal_pwmio_pwmout_get_pin(pwmio_pwmout_obj_t *self) {
    return self->pin;
}

void common_hal_pwmio_pwmout_reset_ok(pwmio_pwmout_obj_t *self) {
    (void)self;
}
