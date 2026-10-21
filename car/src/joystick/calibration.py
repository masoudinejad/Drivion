"""Pure axis identification and calibration, independent of terminal prompts."""

from collections.abc import Mapping
from typing import Protocol

from car.src.configuration.schema import JoystickAxisConfig


class AxisSample(Protocol):
    """Absolute axis information supplied by evdev or a recorded sample."""

    value: int
    min: int
    max: int


def _check_range(centre: AxisSample, sample: AxisSample) -> None:
    if (sample.min, sample.max) != (centre.min, centre.max):
        raise ValueError(
            "Joystick axis range changed. Return to neutral and retry setup."
        )


def identify_axis(
    centre: Mapping[str, AxisSample],
    sample: Mapping[str, AxisSample],
    minimum_excursion: float,
    dominance_ratio: float,
    excluded: tuple[str, ...] = (),
) -> str:
    """Identify the dominant first-endpoint movement using normalized travel.

    Axes already assigned to other controls are excluded. Perpendicular motion
    is allowed if the intended movement dominates it by the configured ratio.
    """
    distances = []
    for name, initial in centre.items():
        if name in excluded or not initial.min < initial.value < initial.max:
            continue
        endpoint = sample[name]
        _check_range(initial, endpoint)
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


def calibrate_axis(
    name: str,
    centre: AxisSample,
    negative: AxisSample,
    positive: AxisSample,
    minimum_excursion: float,
) -> JoystickAxisConfig:
    """Calibrate the identified axis from two opposite endpoint samples.

    Other axes do not participate after identification, so incidental motion
    cannot invalidate a valid opposite endpoint. Bounds may be asymmetric.
    """
    _check_range(centre, negative)
    _check_range(centre, positive)
    low, high = sorted((negative.value, positive.value))
    span = centre.max - centre.min
    if (
        not low < centre.value < high
        or span <= 0
        or (min(centre.value - low, high - centre.value) / span < minimum_excursion)
    ):
        raise ValueError(
            "Reading did not reach the opposite side of the detected axis."
        )
    return JoystickAxisConfig(
        axis=name,
        minimum=low,
        centre=centre.value,
        maximum=high,
        inverted=positive.value < centre.value,
    )
