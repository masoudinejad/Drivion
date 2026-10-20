"""Exercise preview bars, manual verification, inactivity hints and cleanup."""

import io
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from car.src.joystick import ControlInput
from car.system.management.joystick_preview import preview_loop


def test_preview_requires_both_controls_before_enter():
    readings = iter(
        [
            ControlInput(0, 0),
            ControlInput(0, 0),
            ControlInput(0.5, 0),
            ControlInput(0, -0.5),
        ]
    )
    keys = iter(["\n", "\n", "\n"])
    frames = []
    assert preview_loop(
        lambda: next(readings),
        lambda timeout: next(keys),
        lambda *args: frames.append(args),
        refresh_seconds=0.05,
        idle_hint_seconds=5,
        clock=lambda: 0,
    )
    assert frames[0][1:3] == (False, False)
    assert frames[1][1:3] == (True, False)
    assert frames[2][1:3] == (True, True)


def test_inactive_preview_shows_wake_hint_and_allows_cancel():
    times = iter([0, 6])
    frames = []
    assert not preview_loop(
        lambda: ControlInput(0, 0),
        lambda timeout: "\x1b",
        lambda *args: frames.append(args),
        refresh_seconds=0.05,
        idle_hint_seconds=5,
        clock=lambda: next(times),
    )
    assert frames[0][-1]


@pytest.mark.parametrize("key,error", [("\x03", KeyboardInterrupt), ("", RuntimeError)])
def test_preview_cancel_and_closed_input(key, error):
    with pytest.raises(error):
        preview_loop(
            lambda: ControlInput(0, 0),
            lambda timeout: key,
            lambda *args: None,
            refresh_seconds=0.05,
            idle_hint_seconds=5,
        )


def test_preview_restores_terminal_on_read_failure(monkeypatch):
    from car.system.management import joystick_preview as module

    reader = SimpleNamespace(fileno=lambda: 42)
    terminal = io.StringIO()
    terminal.isatty = lambda: True
    restored = []
    saved = object()
    monkeypatch.setattr(
        module,
        "open",
        lambda path, mode="r", **kwargs: nullcontext(
            reader if mode == "r" else terminal
        ),
        raising=False,
    )
    monkeypatch.setattr(module.termios, "tcgetattr", lambda fd: saved)
    monkeypatch.setattr(
        module.termios, "tcsetattr", lambda *args: restored.append(args)
    )
    monkeypatch.setattr(module.tty, "setcbreak", lambda fd: None)
    monkeypatch.setenv("TERM", "xterm")

    def fail(**kwargs):
        raise OSError("disconnected")

    with pytest.raises(OSError, match="disconnected"):
        module.preview_controls(
            SimpleNamespace(read=fail),
            SimpleNamespace(
                allow_reverse=True, speed_mode="accurate", steering_mode="accurate"
            ),
            {
                "preview_refresh_seconds": 0.05,
                "preview_idle_hint_seconds": 5,
            },
        )
    assert restored == [(42, module.termios.TCSADRAIN, saved)]
    assert "\033[?25h" in terminal.getvalue()


def test_fixed_forward_only_can_be_checked_when_initially_held():
    readings = iter([ControlInput(1, 1), ControlInput(0, 0)])
    assert preview_loop(
        lambda: next(readings),
        lambda timeout: "\n",
        lambda *args: None,
        refresh_seconds=0.05,
        idle_hint_seconds=5,
        clock=lambda: 0,
    )
