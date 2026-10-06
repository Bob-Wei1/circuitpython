# SPDX-FileCopyrightText: 2026 Embedder contributors
# SPDX-License-Identifier: MIT
import time

import board
import pwmio
from adafruit_motor import servo

# Measure first without a motor. Verify IO level, servo limits and separate power before attachment.
with pwmio.PWMOut(board.PORT3_04, frequency=50) as pwm:
    motor = servo.Servo(pwm, min_pulse=1000, max_pulse=2000)
    while True:
        for angle in (0, 90, 180):
            motor.angle = angle
            time.sleep(1)
