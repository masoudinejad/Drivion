"""Reusable, display-only terminal monitor for normalized driving demands."""

import math
import os
import shutil
import sys
import textwrap
import time
from pathlib import Path

import tomllib

from .screen import terminal_screen
from .theme import load_theme


def _text(value):
    return "".join(char if char.isprintable() else " " for char in str(value))


def _value(value):
    if value is None:
        return None
    if (
        type(value) not in (int, float)
        or not math.isfinite(value)
        or not -1 <= value <= 1
    ):
        raise ValueError("Monitor demands must be finite values in [-1, 1], or None")
    return float(value)


class DriveMonitor:
    """Render normalized demands without reading devices or controlling the car.

    Mode arguments describe the values supplied by the caller. Accurate modes
    show magnitude; fixed modes show states. ``None`` denotes unavailable data.
    Use ``render`` to embed the display, or a context manager and ``update`` to
    own a live terminal screen. No keyboard input, threads, or hardware access.
    Updates are rate-limited independently of the driving loop; calls must be
    serialized. Pass status text from the source rather than inferring health
    from whether the driver happens to hold a stick still.
    """

    def __init__(
        self,
        *,
        allow_reverse,
        speed_mode,
        steering_mode,
        stream=None,
        styled=None,
        ascii_only=None,
        clock=time.monotonic,
    ):
        if type(allow_reverse) is not bool or any(
            mode not in ("accurate", "fixed") for mode in (speed_mode, steering_mode)
        ):
            raise ValueError("Provide valid reverse and response-mode settings")
        self.allow_reverse = allow_reverse
        self.speed_mode, self.steering_mode = speed_mode, steering_mode
        self.stream = sys.stderr if stream is None else stream
        self.clock = clock
        self.interactive = self.stream.isatty() and os.environ.get("TERM") != "dumb"
        self.theme = load_theme(
            self.interactive and "NO_COLOR" not in os.environ
            if styled is None
            else styled
        )
        if ascii_only is None:
            try:
                "░█│".encode(getattr(self.stream, "encoding", None) or "utf-8")
                ascii_only = False
            except (UnicodeEncodeError, LookupError):
                ascii_only = True
        self.ascii_only = ascii_only
        with Path(__file__).with_name("theme.toml").open("rb") as source:
            settings = tomllib.load(source)["drive_monitor"]
        self.cells = settings["gauge_cells_per_side"]
        self.refresh_seconds = settings["refresh_seconds"]
        self.speed_color = settings["speed_color"]
        self.steering_color = settings["steering_color"]
        self.row_spacing = settings["row_spacing"]
        if (
            self.speed_color not in self.theme
            or self.steering_color not in self.theme
            or type(self.row_spacing) is not int
            or not 0 <= self.row_spacing <= 3
        ):
            raise ValueError("Configure valid monitor colors and row spacing (0 to 3)")
        if (
            type(self.cells) is not int
            or self.cells < 1
            or (
                type(self.refresh_seconds) not in (int, float)
                or not math.isfinite(self.refresh_seconds)
                or self.refresh_seconds <= 0
            )
        ):
            raise ValueError(
                "Configure positive drive monitor dimensions and refresh time"
            )
        self._screen = None
        self._last_draw = None

    def _label(self, value):
        text = _text(value)
        return text.encode("ascii", "replace").decode() if self.ascii_only else text

    def _paint(self, value, style):
        return self.theme[style] + value + self.theme["reset"]

    def _gauge(self, value, cells, signed, color):
        empty, fill, centre = (".", "#", "|") if self.ascii_only else ("░", "█", "│")
        count = 0 if value is None else round(abs(value) * cells)
        active = self._paint(fill * count, color)
        track = lambda size: self._paint(empty * size, "gray")
        if not signed:
            return active + track(cells - count)
        left = (
            track(cells)
            if value is None or value >= 0
            else track(cells - count) + active
        )
        right = (
            track(cells)
            if value is None or value <= 0
            else active + track(cells - count)
        )
        return left + self._paint(centre, "gray") + right

    def _row(
        self, label, value, mode, signed, negative, neutral, positive, columns, color
    ):
        if mode == "fixed":
            states = ([(negative, -1)] if signed else []) + [
                (neutral, 0),
                (positive, 1),
            ]
            state_text = "  ".join(
                self._paint(
                    f"[{name}]" if value == number else name,
                    color if value == number else "gray",
                )
                for name, number in states
            )
            if value is None:
                state_text = self._paint("Unavailable", "gray")
            plain_width = sum(
                len(name) + (2 if value == number else 0) for name, number in states
            ) + 2 * (len(states) - 1)
            if value is None:
                plain_width = len("Unavailable")
            return (
                [self._paint(label, color), state_text]
                if plain_width + 10 > columns
                else [f"{self._paint(f'{label:<10}', color)}{state_text}"]
            )
        number = (
            "  -- " if value is None else f"{value:+.2f}" if signed else f" {value:.2f}"
        )
        low = negative if signed else neutral
        # Fit both gauges to a common compact size; stack in narrow terminals.
        full_cells = min(self.cells, max(1, (columns - 26) // 2))
        cells = full_cells if signed else 2 * full_cells + 1
        gauge = self._gauge(value, cells, signed, color)
        row = f"{self._paint(f'{label:<10}', color)}{low:>4} {gauge} {positive:<3} {self._paint(number, color)}"
        if columns >= 32:
            return [row]
        return [
            self._paint(f"{label} {number}", color),
            f"{low} {self._gauge(value, 2 if signed else 5, signed, color)} {positive}",
        ]

    def render(
        self,
        speed,
        steering,
        *,
        columns=80,
        title="Drive monitor",
        status=None,
        footer=(),
        status_style="dim",
    ):
        """Return a compact frame. Values are demands, not measured speed/angle."""
        speed, steering = _value(speed), _value(steering)
        if speed is not None and not self.allow_reverse and speed < 0:
            raise ValueError("Negative speed is invalid for a forward-only monitor")
        if any(
            mode == "fixed" and value is not None and value not in (-1, 0, 1)
            for value, mode in (
                (speed, self.speed_mode),
                (steering, self.steering_mode),
            )
        ):
            raise ValueError("Fixed modes require direction/state values -1, 0, or 1")
        if status_style not in self.theme:
            raise ValueError("Unknown monitor status style")
        if columns < 24:
            # Keep essential values readable even when gauges cannot fit.
            def compact(label, value, mode, negative, neutral, positive):
                state = (
                    "--"
                    if value is None
                    else negative
                    if value < 0
                    else positive
                    if value > 0
                    else neutral
                )
                text = (
                    f"{value:+.2f}"
                    if mode == "accurate" and value is not None
                    else state
                )
                return f"{label}: {text}"

            lines = [
                self._label(title)[: max(0, columns)],
                self._paint(
                    compact("Speed", speed, self.speed_mode, "REV", "STOP", "FWD"),
                    self.speed_color,
                ),
                *([""] * self.row_spacing),
                self._paint(
                    compact("Steer", steering, self.steering_mode, "L", "0", "R"),
                    self.steering_color,
                ),
            ]
        else:
            lines = [self._paint(self._label(title)[:columns], "bold"), ""]
            lines += self._row(
                "Speed",
                speed,
                self.speed_mode,
                self.allow_reverse,
                "REV",
                "STOP",
                "FWD",
                columns,
                self.speed_color,
            )
            lines += [""] * self.row_spacing
            lines += self._row(
                "Steering",
                steering,
                self.steering_mode,
                True,
                "L",
                "CENTRE",
                "R",
                columns,
                self.steering_color,
            )
        if status:
            lines += [""] + [
                self._paint(part, status_style)
                for part in textwrap.wrap(self._label(status), max(1, columns))
            ]
        if footer:
            lines += [""] + [
                self._paint(part, "dim")
                for line in footer
                for part in textwrap.wrap(self._label(line), max(1, columns))
            ]
        return "\n".join(lines)

    def update(self, speed, steering, *, force=False, **presentation):
        """Draw at the configured UI rate; never wait for keys or sleep."""
        if self._screen is None:
            raise RuntimeError("Use DriveMonitor as a context manager for live updates")
        now = self.clock()
        if (
            not force
            and self._last_draw is not None
            and now - self._last_draw < self.refresh_seconds
        ):
            return False
        if "columns" not in presentation:
            try:
                columns = os.get_terminal_size(self.stream.fileno()).columns
            except (AttributeError, OSError, ValueError):
                columns = 0
            presentation["columns"] = columns or shutil.get_terminal_size().columns
        frame = self.render(speed, steering, **presentation)
        if self.interactive:
            self.stream.write(
                "\033[H"
                + "".join("\r\033[2K" + line + "\n" for line in frame.splitlines())
                + "\033[J"
            )
        else:
            self.stream.write(frame + "\n")
        self.stream.flush()
        self._last_draw = now
        return True

    def __enter__(self):
        if self._screen is not None:
            raise RuntimeError("Drive monitor is already open")
        self._screen = terminal_screen(stream=self.stream)
        self._screen.__enter__()
        self._last_draw = None
        if self.interactive:
            self.stream.write("\033[?25l")
            self.stream.flush()
        return self

    def __exit__(self, *exc):
        try:
            if self.interactive:
                self.stream.write("\033[?25h")
                self.stream.flush()
        finally:
            screen, self._screen = self._screen, None
            if screen is not None:
                screen.__exit__(*exc)
