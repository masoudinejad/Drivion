"""Verify axis detection and endpoint calibration without devices or terminal UI."""

from types import SimpleNamespace

import pytest

from car.src.joystick.calibration import calibrate_axis, identify_axis


def snapshot(speed=0, steering=0):
    return {
        name: SimpleNamespace(value=value, min=-100, max=100)
        for name, value in (("ABS_Y", speed), ("ABS_RX", steering))
    }


def calibrate_samples(centre, negative, positive):
    name = identify_axis(centre, negative, 0.25, 1.5)
    return calibrate_axis(name, centre[name], negative[name], positive[name], 0.25)


@pytest.mark.parametrize(
    "negative,positive",
    [
        (snapshot(), snapshot()),
        (snapshot(-100, -100), snapshot(100, 100)),
        (snapshot(0, 50), snapshot(0, 100)),
    ],
)
def test_calibration_rejects_insufficient_ambiguous_or_wrong_direction(
    negative, positive
):
    with pytest.raises(ValueError):
        calibrate_samples(snapshot(), negative, positive)


@pytest.mark.parametrize(
    "negative,positive,expected,inverted",
    [
        (snapshot(-60, -100), snapshot(60, 100), "ABS_RX", False),
        (snapshot(50, -100), snapshot(30, 100), "ABS_RX", False),
        (snapshot(100, -60), snapshot(-100, 60), "ABS_Y", True),
    ],
)
def test_calibration_tolerates_perpendicular_motion(
    negative, positive, expected, inverted
):
    result = calibrate_samples(snapshot(), negative, positive)
    assert result.axis == expected
    assert result.inverted == inverted
    assert (result.minimum, result.centre, result.maximum) == (-100, 0, 100)


@pytest.mark.parametrize(
    "negative,positive",
    [
        (snapshot(-80, -100), snapshot(80, 100)),  # Near diagonal.
        (snapshot(0, -100), snapshot(0, -60)),  # Same side of the identified axis.
        (snapshot(100, -60), snapshot(100, 60)),  # Strong one-sided interference.
    ],
)
def test_calibration_rejects_ambiguous_or_conflicting_motion(negative, positive):
    with pytest.raises(ValueError):
        calibrate_samples(snapshot(), negative, positive)


def test_calibration_compares_normalized_axis_ranges():
    def values(main, incidental):
        return {
            "ABS_RX": SimpleNamespace(value=main, min=-100, max=100),
            "ABS_RY": SimpleNamespace(value=incidental, min=-10000, max=10000),
        }

    calibration = calibrate_samples(
        values(0, 0), values(-100, -6000), values(100, 6000)
    )
    assert calibration.axis == "ABS_RX"
