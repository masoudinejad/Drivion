"""Convert normalized driver demand to the existing physical-angle protocol."""

import math


def steering_degrees(value: float, parameters: dict) -> float:
    """Map -1/0/+1 to left limit/straight/right limit from firmware settings.

    Clamp finite demands to the calibrated range. Reject non-finite values before
    sending; they must never renew the Arduino's command watchdog.
    """
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError("Normalized steering must be finite")
    left, right = parameters["STEERING_LEFT_DEG"], parameters["STEERING_RIGHT_DEG"]
    if not 0 < left <= 327.68 or not 0 < right <= 327.67:
        raise ValueError("Invalid physical steering limits")
    value = max(-1.0, min(1.0, value))
    return value * (left if value < 0 else right)
