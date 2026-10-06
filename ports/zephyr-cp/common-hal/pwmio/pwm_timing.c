// SPDX-FileCopyrightText: 2026 Embedder contributors
// SPDX-License-Identifier: MIT
#include "common-hal/pwmio/pwm_timing.h"
#include <stddef.h>

bool pwmio_compute_timing(uint32_t frequency, pwmio_timing_t *timing) {
    bool found = false;
    uint64_t best_error = UINT64_C(0);
    pwmio_timing_t best = {0};

    // TOP >= 4 follows the native Nordic port's conservative supported range.
    if ((timing != NULL) && (frequency >= UINT32_C(4)) &&
        (frequency <= (PWMIO_NRF_CLOCK_HZ / PWMIO_NRF_TOP_MIN))) {
        for (uint32_t prescaler = 0U; prescaler <= PWMIO_NRF_PRESCALER_MAX; prescaler++) {
            const uint32_t divisor = UINT32_C(1) << prescaler;
            const uint32_t lower = PWMIO_NRF_CLOCK_HZ / (frequency * divisor);
            for (uint32_t adjacent = 0U; adjacent < UINT32_C(2); adjacent++) {
                const uint32_t top = lower + adjacent;
                if ((top >= PWMIO_NRF_TOP_MIN) && (top <= PWMIO_NRF_TOP_MAX)) {
                    const uint32_t period = top * divisor;
                    const uint64_t product = (uint64_t)frequency * (uint64_t)period;
                    const uint64_t clock = (uint64_t)PWMIO_NRF_CLOCK_HZ;
                    const uint64_t error = (product >= clock) ? (product - clock) : (clock - product);
                    // Compare frequency errors as rational numbers, without floating point.
                    if ((!found) || ((error * (uint64_t)best.period_cycles) <
                        (best_error * (uint64_t)period)) ||
                        (((error * (uint64_t)best.period_cycles) ==
                        (best_error * (uint64_t)period)) && (top > (uint32_t)best.countertop))) {
                        best.period_cycles = period;
                        best.frequency = (PWMIO_NRF_CLOCK_HZ + (period / UINT32_C(2))) / period;
                        best.countertop = (uint16_t)top;
                        best.prescaler = (uint8_t)prescaler;
                        best_error = error;
                        found = true;
                    }
                }
            }
        }
    }
    if (found) {
        *timing = best;
    }
    return found;
}

uint32_t pwmio_compute_pulse(const pwmio_timing_t *timing, uint16_t duty) {
    // The largest product plus rounding is below 2^31; all shifts are <= 7.
    const uint32_t compare = (((uint32_t)duty * (uint32_t)timing->countertop) +
        UINT32_C(32767)) / UINT32_C(65535);
    return compare << (uint32_t)timing->prescaler;
}
