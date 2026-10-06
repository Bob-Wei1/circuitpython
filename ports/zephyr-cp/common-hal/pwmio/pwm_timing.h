// SPDX-FileCopyrightText: 2026 Embedder contributors
// SPDX-License-Identifier: MIT
#ifndef ZEPHYR_CP_PWM_TIMING_H
#define ZEPHYR_CP_PWM_TIMING_H

#include <stdbool.h>
#include <stdint.h>

#define PWMIO_NRF_CLOCK_HZ UINT32_C(16000000)
#define PWMIO_NRF_TOP_MIN UINT32_C(4)
#define PWMIO_NRF_TOP_MAX UINT32_C(32767)
#define PWMIO_NRF_PRESCALER_MAX UINT32_C(7)

typedef struct {
    uint32_t period_cycles;
    uint32_t frequency;
    uint16_t countertop;
    uint8_t prescaler;
} pwmio_timing_t;

bool pwmio_compute_timing(uint32_t frequency, pwmio_timing_t *timing);
uint32_t pwmio_compute_pulse(const pwmio_timing_t *timing, uint16_t duty);

#endif
