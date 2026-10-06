// SPDX-FileCopyrightText: 2026 Embedder contributors
// SPDX-License-Identifier: MIT
#ifndef ZEPHYR_CP_PWMOUT_H
#define ZEPHYR_CP_PWMOUT_H

#include <stdbool.h>
#include <stdint.h>
#include <zephyr/device.h>
#include "py/obj.h"
#include "common-hal/microcontroller/Pin.h"
#include "common-hal/pwmio/pwm_timing.h"

typedef struct {
    mp_obj_base_t base;
    const mcu_pin_obj_t *pin;
    const struct device *device;
    pwmio_timing_t timing;
    uint32_t pulse_cycles;
    uint16_t duty_cycle;
    bool variable_frequency;
    bool programmed;
} pwmio_pwmout_obj_t;

#endif
