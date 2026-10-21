"""Live normalized control bars for checking unsaved joystick settings."""

import time

from ..ui.drive_monitor import DriveMonitor
from ..ui.terminal import terminal_input


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


def preview_controls(joystick, controls, settings, *, read=None):
    """Preview controls, optionally instrumenting reads through a supplied callable."""
    from car.src.configuration.schema import JoystickSetupConfig

    settings = JoystickSetupConfig.model_validate(settings)
    refresh, idle = settings.preview_refresh_seconds, settings.preview_idle_hint_seconds
    with terminal_input() as terminal:
        monitor = DriveMonitor(
            allow_reverse=controls.allow_reverse,
            speed_mode=controls.speed_mode,
            steering_mode=controls.steering_mode,
            stream=terminal.stream,
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

        with monitor:
            return preview_loop(
                (lambda: joystick.read(controls=controls)) if read is None else read,
                terminal.key,
                draw,
                refresh_seconds=refresh,
                idle_hint_seconds=idle,
            )
