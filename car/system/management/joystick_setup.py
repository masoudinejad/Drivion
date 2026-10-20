"""Guided stick calibration and control interpretation settings."""

import math
from pathlib import Path

import tomllib

from ..ui.navigation import prompt_number, select_item
from .joystick_preview import preview_controls


def calibrate_axis(centre, negative, positive, minimum_excursion, dominance_ratio):
    """Identify opposite travel on the same dominant axis at both endpoints.

    Compare movement as a fraction of each driver's axis range, so different
    raw resolutions cannot bias selection. Incidental perpendicular movement is
    permitted; near-diagonal or conflicting endpoint samples remain ambiguous.
    """
    from car.src.configuration.schema import JoystickAxisConfig

    movements = {}
    for name, initial in centre.items():
        before, after = negative[name], positive[name]
        if (before.min, before.max) != (initial.min, initial.max) or (
            after.min,
            after.max,
        ) != (initial.min, initial.max):
            raise ValueError("Joystick axis ranges changed during calibration.")
        span = initial.max - initial.min
        if span > 0:
            movements[name] = (
                abs(before.value - initial.value) / span,
                abs(after.value - initial.value) / span,
            )
    candidates = []
    for name, distances in movements.items():
        initial, before, after = centre[name], negative[name], positive[name]
        low, high = sorted((before.value, after.value))
        if not low < initial.value < high or min(distances) < minimum_excursion:
            continue
        if any(
            distance
            < dominance_ratio
            * max(
                (other[index] for axis, other in movements.items() if axis != name),
                default=0.0,
            )
            for index, distance in enumerate(distances)
        ):
            continue
        candidates.append(
            JoystickAxisConfig(
                axis=name,
                minimum=low,
                centre=initial.value,
                maximum=high,
                inverted=after.value < initial.value,
            )
        )
    if len(candidates) != 1:
        raise ValueError(
            "Could not identify a dominant stick axis. Retry mainly along the requested "
            "direction; small perpendicular movement is fine, but avoid diagonals."
        )
    return candidates[0]


def capture_reading(instruction):
    """Enter captures immediately; Back/Escape cancels without typed answers."""
    return select_item(instruction, ["Capture reading"]) == 0


def save_settings(summary):
    """Use a selectable save action rather than a typed boolean answer."""
    return select_item(summary, ["Save settings"]) == 0


def identify_axis(centre, sample, minimum_excursion, dominance_ratio, excluded=()):
    """Lock the dominant axis from one endpoint, excluding assigned controls."""
    distances = []
    for name, initial in centre.items():
        if name in excluded or not initial.min < initial.value < initial.max:
            continue
        endpoint = sample[name]
        if (endpoint.min, endpoint.max) != (initial.min, initial.max):
            raise ValueError("Axis range changed; return to neutral and retry setup.")
        distance = abs(endpoint.value - initial.value) / (initial.max - initial.min)
        distances.append((distance, name))
    distances.sort(reverse=True)
    if not distances or distances[0][0] < minimum_excursion:
        raise ValueError(
            "Not enough travel. If nothing responds, wake the controller and check its connection. "
            "Then hold the requested stick fully in that direction."
        )
    if len(distances) > 1 and distances[0][0] < dominance_ratio * distances[1][0]:
        raise ValueError(
            "Movement is too diagonal. Move mainly in the requested direction."
        )
    return distances[0][1]


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
                {name: centre[name]},
                {name: negative[name]},
                {name: positive[name]},
                excursion,
                dominance,
            )
        except ValueError:
            message = (
                "Reading did not reach the opposite side of the detected axis. "
                "The previous reading is kept. If nothing responds, wake the controller. "
                + positive_instruction
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
    from car.src.config import load_config, update_config
    from car.src.joystick import Joystick

    root = Path(car_root)
    path = root / "config.toml"
    config = load_config(path).joystick
    with (root / "system/pyproject.toml").open("rb") as stream:
        settings = tomllib.load(stream)["tool"]["drivion"]["joystick_setup"]
    excursion = settings["minimum_axis_excursion"]
    dominance = settings["axis_dominance_ratio"]
    if type(excursion) not in (int, float) or not 0 < excursion <= 0.5:
        raise ValueError("Configure a minimum axis excursion in (0, 0.5].")
    if (
        type(dominance) not in (int, float)
        or not math.isfinite(dominance)
        or dominance <= 1
    ):
        raise ValueError("Configure a finite axis dominance ratio greater than 1.")
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
        dead_zone = number(
            "Neutral dead zone as a fraction from 0 to below 1 (e.g. 0.05)"
        )
        if dead_zone is None:
            return
        controls = config.controls.with_overrides(
            steering=steering,
            speed=speed,
            allow_reverse=reverse == 0,
            steering_mode="accurate" if steering_mode == 0 else "fixed",
            speed_mode="accurate" if speed_mode == 0 else "fixed",
            dead_zone=dead_zone,
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
