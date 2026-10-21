"""Shared validation of firmware parameter values, independent of tooling."""

import math
import re


def validate_parameter_values(firmwares):
    """Keep application TOML limited to scalar defaults, not firmware metadata."""
    if not isinstance(firmwares, dict):
        raise TypeError("Firmware defaults must be a TOML table")
    for name, values in firmwares.items():
        if not isinstance(name, str) or not re.fullmatch(
            r"[A-Za-z][A-Za-z0-9_-]*", name
        ):
            raise ValueError("Firmware names must be safe identifiers")
        if not isinstance(values, dict):
            raise TypeError("Each firmware must contain its parameter defaults")
        for key, value in values.items():
            if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key) or key.startswith("DRIVION_"):
                raise ValueError(
                    "Firmware defaults must be uppercase parameter names, excluding DRIVION_"
                )
            if type(value) not in (str, bool, int, float):
                raise ValueError("Firmware defaults must be scalar values")
            if type(value) is float and not math.isfinite(value):
                raise ValueError("Firmware numeric defaults must be finite")
        if name == "steering":
            validate_steering(values)


def validate_steering(values):
    """Validate related calibration fields before saving or compiling firmware."""

    def number(key, minimum, maximum):
        if key not in values:
            raise ValueError(f"Missing steering parameter: {key}")
        value = values[key]
        if (
            type(value) not in (int, float)
            or not math.isfinite(value)
            or not minimum <= value <= maximum
        ):
            raise ValueError(f"{key} must be between {minimum} and {maximum}")
        return value

    number("STEERING_LEFT_DEG", 0.01, 327.68)
    number("STEERING_RIGHT_DEG", 0.01, 327.67)
    left, center, right = (
        number(key, 0, 180)
        for key in ("SERVO_LEFT_DEG", "SERVO_CENTER_DEG", "SERVO_RIGHT_DEG")
    )
    if not (left < center < right or left > center > right):
        raise ValueError(
            "Servo straight position must lie strictly between left and right"
        )
    for key, minimum, maximum in (
        ("SERVO_PIN", 2, 19),
        ("CALIBRATION_STEP_US", 1, 100),
        ("STEERING_TIMEOUT_MS", 1, 2147483647),
        ("SERVO_MIN_US", 544, 2400),
        ("SERVO_MAX_US", 544, 2400),
    ):
        number(key, minimum, maximum)
        if type(values[key]) is not int:
            raise ValueError(f"{key} must be an integer")
    if values["SERVO_MIN_US"] >= values["SERVO_MAX_US"]:
        raise ValueError("Servo minimum pulse must be less than maximum pulse")
