"""Verify shared single-key input and terminal lifetime for live views."""

import io
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from car.system.ui import terminal as module


@pytest.mark.parametrize(
    "data,expected,error",
    [
        (b"\r", "\r", None),
        (b"\x1b", "\x1b", None),
        (b"\x03", None, KeyboardInterrupt),
        (b"", None, RuntimeError),
    ],
)
def test_keyboard_data_and_cancellation(monkeypatch, data, expected, error):
    reader = SimpleNamespace(fileno=lambda: 42)
    keyboard = module.TerminalInput(reader, io.StringIO())
    monkeypatch.setattr(module.select, "select", lambda *args: ([reader], [], []))
    monkeypatch.setattr(module.os, "read", lambda fd, size: data)
    if error is not None:
        with pytest.raises(error):
            keyboard.key(0.1)
    else:
        assert keyboard.key(0.1) == expected


def test_no_keyboard_data_does_not_read(monkeypatch):
    monkeypatch.setattr(module.select, "select", lambda *args: ([], [], []))
    keyboard = module.TerminalInput(SimpleNamespace(), io.StringIO())
    assert keyboard.key(0.1) is None


@pytest.mark.parametrize("fail_during_entry", [False, True])
def test_input_mode_restored_on_failure(monkeypatch, fail_during_entry):
    reader = SimpleNamespace(fileno=lambda: 42)
    stream = io.StringIO()
    restored = []
    monkeypatch.setenv("TERM", "xterm")
    monkeypatch.setattr(
        module,
        "open",
        lambda path, mode="r", **kwargs: nullcontext(reader if mode == "r" else stream),
        raising=False,
    )
    monkeypatch.setattr(module.termios, "tcgetattr", lambda fd: "original-mode")
    monkeypatch.setattr(
        module.termios, "tcsetattr", lambda *args: restored.append(args)
    )

    def enter(fd):
        if fail_during_entry:
            raise OSError("entry failed")

    monkeypatch.setattr(module.tty, "setcbreak", enter)
    with pytest.raises(OSError), module.terminal_input():
        raise OSError("view failed")
    assert restored == [(42, module.termios.TCSADRAIN, "original-mode")]
