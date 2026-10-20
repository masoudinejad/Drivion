"""Live normalized control bars for checking unsaved joystick settings."""

import os
import select
import termios
import time
import tty

from ..ui.drive_monitor import DriveMonitor


def preview_loop(
    read, key, draw, *, refresh_seconds, idle_hint_seconds, clock=time.monotonic
):
    """Exercise both controls before Enter; Escape cancels without saving.

    ``key`` waits at most refresh_seconds. No movement is evidence of inactivity,
    not a reliable indication of a sleeping wireless controller.
    """
    previous = read()
    last_change = clock()
    speed_tested = steering_tested = False
    while True:
        current = read()
        if current != previous:
            last_change = clock()
        if current.speed != previous.speed:
            speed_tested = True
        if current.steering != previous.steering:
            steering_tested = True
        draw(
            current,
            speed_tested,
            steering_tested,
            clock() - last_change >= idle_hint_seconds,
        )
        pressed = key(refresh_seconds)
        if pressed in ("\r", "\n") and speed_tested and steering_tested:
            return True
        if pressed == "\x1b":
            return False
        if pressed == "\x03":
            raise KeyboardInterrupt
        if pressed == "":
            raise RuntimeError("Terminal input closed during joystick preview.")
        previous = current


def preview_controls(joystick, controls, settings):
    """Preview through the Joystick class in the shared management screen."""
    refresh = settings["preview_refresh_seconds"]
    idle = settings["preview_idle_hint_seconds"]
    if not 0 < refresh <= 1 or not 0 < idle < float("inf"):
        raise ValueError("Configure finite positive joystick preview timings.")
    if os.environ.get("TERM") == "dumb":
        raise RuntimeError("Joystick preview requires an interactive ANSI terminal.")
    with (
        open("/dev/tty", encoding="utf-8") as reader,
        open("/dev/tty", "w", encoding="utf-8", buffering=1) as terminal,
    ):
        saved = termios.tcgetattr(reader.fileno())
        monitor = DriveMonitor(
            allow_reverse=controls.allow_reverse,
            speed_mode=controls.speed_mode,
            steering_mode=controls.steering_mode,
            stream=terminal,
        )

        def draw(current, speed_tested, steering_tested, inactive):
            speed_mark = "checked" if speed_tested else "move left stick"
            steering_mark = "checked" if steering_tested else "move right stick"
            status = f"Speed: {speed_mark}   Steering: {steering_mark}"
            if inactive:
                status += " | No changes: wake controller if unresponsive"
            monitor.update(
                current.speed,
                current.steering,
                title="Check controls",
                status=status,
                status_style="green" if speed_tested and steering_tested else "dim",
                footer=("Enter Continue after checking both / Esc Cancel",),
            )

        def key(timeout):
            ready, _, _ = select.select([reader], [], [], timeout)
            return reader.read(1) if ready else None

        with monitor:
            try:
                tty.setcbreak(reader.fileno())
                return preview_loop(
                    lambda: joystick.read(controls=controls),
                    key,
                    draw,
                    refresh_seconds=refresh,
                    idle_hint_seconds=idle,
                )
            finally:
                termios.tcsetattr(reader.fileno(), termios.TCSADRAIN, saved)
