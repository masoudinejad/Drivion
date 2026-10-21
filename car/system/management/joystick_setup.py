"""Guided stick calibration and control interpretation settings."""

from pathlib import Path

import tomllib

from ..ui.navigation import prompt_number, select_item
from .joystick_preview import preview_controls


def capture_reading(instruction):
    """Enter captures immediately; Back/Escape cancels without typed answers."""
    return select_item(instruction, ["Capture reading"]) == 0


def save_settings(summary):
    """Use a selectable save action rather than a typed boolean answer."""
    return select_item(summary, ["Save settings"]) == 0


def capture_axis(
    joystick,
    centre,
    negative_instruction,
    positive_instruction,
    excursion,
    dominance,
    ask,
    excluded=(),
):
    """Retain a valid first endpoint while retrying the opposite endpoint."""
    from car.src.joystick.calibration import calibrate_axis, identify_axis

    message = negative_instruction
    while True:
        if not ask(message):
            return None
        negative = joystick.axis_snapshot()
        try:
            name = identify_axis(centre, negative, excursion, dominance, excluded)
            break
        except ValueError as error:
            message = f"{error} {negative_instruction}"
    message = positive_instruction
    while True:
        if not ask(message):
            return None
        positive = joystick.axis_snapshot()
        try:
            return calibrate_axis(
                name,
                centre[name],
                negative[name],
                positive[name],
                excursion,
            )
        except ValueError as error:
            message = (
                f"{error} The previous reading is kept. "
                "If nothing responds, wake the controller. " + positive_instruction
            )


def configure_controls(
    car_root,
    *,
    select=select_item,
    ask=capture_reading,
    number=prompt_number,
    factory=None,
    save=save_settings,
    preview=preview_controls,
):
    """Capture one step at a time and save the complete setup atomically.

    Invalid endpoint readings repeat only that step. Back/Ignore leaves the
    configuration untouched. I/O failures still abort and release the device.
    """
    from pydantic import ValidationError

    from car.src.config import load_config, update_config
    from car.src.configuration.schema import JoystickSetupConfig
    from car.src.joystick import Joystick

    root = Path(car_root)
    path = root / "config.toml"
    config = load_config(path).joystick
    with (root / "system/pyproject.toml").open("rb") as stream:
        settings = JoystickSetupConfig.model_validate(
            tomllib.load(stream)["tool"]["drivion"]["joystick_setup"]
        )
    excursion = settings.minimum_axis_excursion
    dominance = settings.axis_dominance_ratio
    factory = Joystick if factory is None else factory
    with factory(config, for_setup=True) as joystick:
        if not ask(
            "Joystick initialized. Wake the controller if idle, check its connection, "
            "then release both sticks to centre."
        ):
            return
        centre = joystick.axis_snapshot()
        steering = capture_axis(
            joystick,
            centre,
            "Hold the RIGHT stick fully LEFT.",
            "Hold the RIGHT stick fully RIGHT.",
            excursion,
            dominance,
            ask,
        )
        if steering is None:
            return
        if not ask(
            "Steering captured. Release both sticks to centre before speed setup."
        ):
            return
        speed_centre = joystick.axis_snapshot()
        speed = capture_axis(
            joystick,
            speed_centre,
            "Hold the LEFT stick fully DOWN (backward).",
            "Hold the LEFT stick fully UP (forward).",
            excursion,
            dominance,
            ask,
            excluded=(steering.axis,),
        )
        if speed is None:
            return
        steering_mode = select(
            "Steering response", ["Accurate (proportional)", "Fixed (direction only)"]
        )
        if steering_mode is None:
            return
        speed_mode = select(
            "Speed response", ["Accurate (proportional)", "Fixed (single speed)"]
        )
        if speed_mode is None:
            return
        reverse = select("Reverse driving", ["Allow backward movement", "Forward only"])
        if reverse is None:
            return
        if any(choice not in (0, 1) for choice in (steering_mode, speed_mode, reverse)):
            raise ValueError("Invalid control setting selection")
        base = config.controls.with_overrides(
            steering=steering,
            speed=speed,
            allow_reverse=reverse == 0,
            steering_mode="accurate" if steering_mode == 0 else "fixed",
            speed_mode="accurate" if speed_mode == 0 else "fixed",
        )
        question = "Neutral dead zone as a fraction from 0 to below 1 (e.g. 0.05)"
        while True:
            dead_zone = number(question)
            if dead_zone is None:
                return
            try:
                controls = base.with_overrides(dead_zone=dead_zone)
                break
            except ValidationError:
                question = (
                    "Dead zone must be finite, at least 0 and below 1. "
                    "Calibration is kept. Enter a valid dead zone (e.g. 0.05)"
                )
        if not preview(joystick, controls, settings):
            return
        reverse_label = "enabled" if controls.allow_reverse else "disabled"
        if not save(
            f"Save controls: steering {controls.steering_mode}, speed {controls.speed_mode}, "
            f"reverse {reverse_label}, dead zone {controls.dead_zone:g}?"
        ):
            return
        joystick.axis_snapshot()
        update_config("joystick.controls", controls.model_dump(exclude_none=True), path)
