"""Edit servo calibration atomically through the existing management UI."""

import tomllib
from pathlib import Path

from car.src.configuration.firmware import validate_steering

from ...ui.navigation import confirm, prompt_number, show_page
from ..firmware.definitions import load_firmware


def configure_steering(
    car_root, *, prompt=prompt_number, approve=confirm, display=show_page
):
    """Collect a complete candidate; cancellation or invalid input never saves."""
    from car.src.config import update_config

    root = Path(car_root)
    path = root / "config.toml"
    try:
        with path.open("rb") as stream:
            values = dict(tomllib.load(stream)["firmware"]["steering"])
        questions = (
            (
                "STEERING_LEFT_DEG",
                "Maximum physical left steering angle (positive degrees)",
            ),
            (
                "STEERING_RIGHT_DEG",
                "Maximum physical right steering angle (positive degrees)",
            ),
            ("SERVO_LEFT_DEG", "Servo position at maximum left (0-180 degrees)"),
            ("SERVO_CENTER_DEG", "Servo position for straight (0-180 degrees)"),
            (
                "SERVO_RIGHT_DEG",
                "Servo position at maximum right (0-180 degrees; may be less than straight)",
            ),
            (
                "SERVO_PIN",
                "Nano servo signal pin (2-19; D9 recommended, D0/D1 reserved for serial)",
            ),
            ("STEERING_TIMEOUT_MS", "No steering update timeout (milliseconds)"),
            (
                "SERVO_MIN_US",
                "Servo pulse at 0 degrees (microseconds; consult servo datasheet)",
            ),
            (
                "SERVO_MAX_US",
                "Servo pulse at 180 degrees (microseconds; consult servo datasheet)",
            ),
        )
        for key, question in questions:
            answer = prompt(
                f"{question} [current: {values[key]}; Ignore keeps current]"
            )
            if answer is not None:
                if type(values[key]) is int:
                    if not answer.is_integer():
                        raise ValueError(f"{key} must be an integer")
                    answer = int(answer)
                values[key] = answer
        validate_steering(values)
        # Advertise the same maximum lease as the steering watchdog. The sender
        # may still choose an earlier command expiry for added safety.
        values["COMMAND_TIMEOUT_MS"] = values["STEERING_TIMEOUT_MS"]
        load_firmware("steering", root, values)
        summary = "\n".join(f"{key} = {value}" for key, value in values.items())
        display("Steering calibration preview", summary)
        if not approve(
            "Save steering calibration? Apply with Arduino -> Change firmware -> steering."
        ):
            return
        update_config("firmware.steering", values, path)
        display(
            "Steering settings saved",
            "Compile and flash the steering firmware to apply these settings. Restart the driving application after flashing.",
        )
    except (OSError, ValueError, TypeError, KeyError) as error:
        display("Steering configuration failed", str(error))
