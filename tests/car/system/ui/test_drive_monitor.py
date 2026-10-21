"""Verify the general drive display independently of joystick or calibration."""

import io
from itertools import product

import pytest

from car.system.ui.drive_monitor import DriveMonitor


def monitor(**overrides):
    values = {
        "allow_reverse": True,
        "speed_mode": "accurate",
        "steering_mode": "accurate",
        "stream": io.StringIO(),
        "styled": False,
    }
    values.update(overrides)
    return DriveMonitor(**values)


def test_accurate_signed_gauges_and_colours():
    display = monitor(styled=True)
    frame = display.render(0.7, -0.3)
    assert "░░░░░░░░░░" in frame and "███████" in frame
    assert "+0.70" in frame and "-0.30" in frame
    assert "REV" in frame and "FWD" in frame
    assert "\033[36m" in frame and "\033[90m" in frame
    assert len(frame.splitlines()) == 5
    assert "\033[36m" in frame.splitlines()[2]
    assert frame.splitlines()[3] == ""
    assert "\033[33m" in frame.splitlines()[4]


def test_forward_only_uses_whole_unsigned_gauge():
    display = monitor(allow_reverse=False)
    frame = display.render(1, 0)
    speed = frame.splitlines()[2]
    assert "STOP" in speed and "FWD" in speed and "REV" not in speed
    assert "│" not in speed
    assert "█" * 21 in speed
    with pytest.raises(ValueError):
        display.render(-0.1, 0)


@pytest.mark.parametrize(
    "allow_reverse,speed_mode,steering_mode",
    list(product([False, True], ["accurate", "fixed"], ["accurate", "fixed"])),
)
def test_all_response_mode_combinations(allow_reverse, speed_mode, steering_mode):
    display = monitor(
        allow_reverse=allow_reverse, speed_mode=speed_mode, steering_mode=steering_mode
    )
    frame = display.render(1, -1)
    speed, _, steering = frame.splitlines()[2:5]
    assert ("REV" in speed) == allow_reverse
    assert ("1.00" in speed) == (speed_mode == "accurate")
    assert ("-1.00" in steering) == (steering_mode == "accurate")
    if speed_mode == "fixed":
        assert "[FWD]" in speed
    if steering_mode == "fixed":
        assert "[L]" in steering


@pytest.mark.parametrize("columns", [20, 24, 32, 40, 80])
def test_responsive_essential_rows_fit(columns):
    for reverse, speed_mode, steering_mode in product(
        [True, False], ["accurate", "fixed"], ["accurate", "fixed"]
    ):
        frame = monitor(
            allow_reverse=reverse, speed_mode=speed_mode, steering_mode=steering_mode
        ).render(
            0 if speed_mode == "fixed" else 0.5,
            0 if steering_mode == "fixed" else -0.5,
            columns=columns,
        )
        assert all(len(line) <= columns for line in frame.splitlines())


def test_unknown_values_are_not_shown_as_zero():
    assert "--" in monitor().render(None, None)
    frame = monitor(speed_mode="fixed", steering_mode="fixed").render(None, None)
    assert frame.count("Unavailable") == 2


@pytest.mark.parametrize("value", [float("nan"), float("inf"), 2, "0.5", True])
def test_invalid_input_rejected(value):
    with pytest.raises(ValueError):
        monitor().render(value, 0)


def test_ascii_and_no_colour(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    output = monitor(ascii_only=True).render(0.5, -1)
    assert "#" in output and "." in output and "|" in output
    assert output.isascii() and "\033" not in output


def test_does_not_allow_fractional_fixed_inputs_even_in_narrow_terminal():
    with pytest.raises(ValueError):
        monitor(speed_mode="fixed").render(0.4, 0, columns=20)


def test_display_rate_does_not_change_or_poll_source():
    times = iter([0, 0.01, 0.2])
    stream = io.StringIO()
    with monitor(stream=stream, clock=lambda: next(times)) as display:
        assert display.update(0, 0)
        assert not display.update(1, 1)
        assert display.update(0.5, -0.5)
    assert "+0.50" in stream.getvalue() and "+1.00" not in stream.getvalue()
    assert "\033" not in stream.getvalue()
    with pytest.raises(RuntimeError):
        display.update(0, 0)


def test_terminal_restores_on_failure(monkeypatch):
    monkeypatch.setenv("TERM", "xterm")
    monkeypatch.delenv("DRIVION_UI_SCREEN_ACTIVE", raising=False)
    stream = io.StringIO()
    stream.isatty = lambda: True
    with pytest.raises(RuntimeError), monitor(stream=stream) as display:
        display.update(0.5, -0.5)
        raise RuntimeError("drive failure")
    assert stream.getvalue().endswith("\033[?25h\033[?1049l")
    assert "DRIVION_UI_SCREEN_ACTIVE" not in __import__("os").environ


def test_status_text_cannot_inject_terminal_commands():
    frame = monitor().render(0, 0, status="Bad\033[2J\nstatus")
    assert "\033" not in frame


def test_live_width_uses_actual_output_terminal(monkeypatch):
    import os

    from car.system.ui import drive_monitor as module

    stream = io.StringIO()
    stream.fileno = lambda: 42
    monkeypatch.setattr(
        module.os, "get_terminal_size", lambda fd: os.terminal_size((32, 24))
    )
    monkeypatch.setattr(
        module.shutil, "get_terminal_size", lambda: os.terminal_size((80, 24))
    )
    with monitor(stream=stream) as display:
        display.update(0.7, -0.3)
    assert all(len(line) <= 32 for line in stream.getvalue().splitlines())
