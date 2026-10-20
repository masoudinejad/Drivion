"""Live normalized control bars for checking unsaved joystick settings."""

import os
import select
import shutil
import termios
import time
import tty

from ..ui.screen import terminal_screen
from ..ui.theme import load_theme


def control_bar(value, half_width):
    """Draw a signed bar around neutral; only the active side is filled."""
    count = round(min(1.0, abs(value)) * half_width)
    left = " " * (half_width - count) + "#" * count if value < 0 else " " * half_width
    right = "#" * count + " " * (half_width - count) if value > 0 else " " * half_width
    return f"[{left}|{right}]"


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
        theme = load_theme("NO_COLOR" not in os.environ)

        def draw(current, speed_tested, steering_tested, inactive):
            width = max(2, min(20, (shutil.get_terminal_size().columns - 5) // 2))
            speed_direction = (
                "Forward"
                if current.speed > 0
                else "Backward"
                if current.speed < 0
                else "Stopped"
            )
            steering_direction = (
                "Right"
                if current.steering > 0
                else "Left"
                if current.steering < 0
                else "Centre"
            )
            lines = [
                f"{theme['bold']}Check joystick controls{theme['reset']}",
                "",
                "Move LEFT stick up/down for speed.",
                "Move RIGHT stick left/right for steering.",
                "Preview only: the car is not driven.",
                "",
                f"Speed: {current.speed:+.2f} {speed_direction}",
                f"{theme['cyan']}{control_bar(current.speed, width)}{theme['reset']}",
                "Backward (-) / Forward (+)",
                "",
                f"Steering: {current.steering:+.2f} {steering_direction}",
                f"{theme['cyan']}{control_bar(current.steering, width)}{theme['reset']}",
                "Left (-) / Right (+)",
                "",
                f"Speed checked: {'yes' if speed_tested else 'move left stick forward'}",
                f"Steering checked: {'yes' if steering_tested else 'move right stick'}",
                "Enter: continue after checking both / Esc: cancel",
            ]
            if inactive:
                lines += [
                    "",
                    "No recent control changes. If sticks do not respond,",
                    "wake the controller and check its wireless connection.",
                ]
            terminal.write(
                "\033[H"
                + "".join("\r\033[2K" + line + "\n" for line in lines)
                + "\033[J"
            )
            terminal.flush()

        def key(timeout):
            ready, _, _ = select.select([reader], [], [], timeout)
            return reader.read(1) if ready else None

        with terminal_screen(stream=terminal):
            try:
                tty.setcbreak(reader.fileno())
                terminal.write("\033[?25l")
                terminal.flush()
                return preview_loop(
                    lambda: joystick.read(controls=controls),
                    key,
                    draw,
                    refresh_seconds=refresh,
                    idle_hint_seconds=idle,
                )
            finally:
                termios.tcsetattr(reader.fileno(), termios.TCSADRAIN, saved)
                terminal.write("\033[?25h")
                terminal.flush()
