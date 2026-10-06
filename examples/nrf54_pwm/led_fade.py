# SPDX-FileCopyrightText: 2026 Embedder contributors
# SPDX-License-Identifier: MIT
import time

import board
import pwmio

# LED0 is P1.22 on the LM20 DK; the scope remains on the separate P3.04 output.
with pwmio.PWMOut(board.LED0, frequency=500) as led:
    while True:
        for duty in range(0, 65536, 512):
            led.duty_cycle = duty
            time.sleep(0.005)
        for duty in range(65535, -1, -512):
            led.duty_cycle = duty
            time.sleep(0.005)
