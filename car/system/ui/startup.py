"""Compact terminal startup display for the driving entry point."""

import logging
import os
import shutil
import sys
from pathlib import Path

import tomllib

from .progress import run_background
from .theme import load_theme


def _prepare_banner(styled=True):
    """Render configured block glyphs, measuring width before adding ANSI styles."""
    with Path(__file__).with_name("theme.toml").open("rb") as source:
        config = tomllib.load(source)["banner"]
    glyphs = [config["glyphs"][letter] for letter in "DRIVION"]
    width = sum(len(glyph[0]) for glyph in glyphs) + len(glyphs) - 1
    if width + 2 <= shutil.get_terminal_size().columns:
        lines = []
        for row in range(len(glyphs[0])):
            parts = []
            for index, glyph in enumerate(glyphs):
                prefix = "muted" if index < config["muted_letters"] else "bright"
                foreground = ";".join(map(str, config[f"{prefix}_rgb"]))
                shadow = ";".join(map(str, config[f"{prefix}_shadow_rgb"]))
                text = ""
                for char in glyph[row]:
                    if styled:
                        background = f"\033[48;2;{shadow}m" if char in "_^" else ""
                        text += f"\033[38;2;{foreground}m{background}"
                    text += {"_": " ", "^": "▀"}.get(char, char)
                    if styled:
                        text += "\033[0m"
                parts.append(text)
            lines.append(" ".join(parts))
        return lines
    return ["DRIVION"]


def show_startup(report=None):
    """Display the central evaluation snapshot without probing hardware again."""
    interactive = sys.stdout.isatty() and os.environ.get("TERM") != "dumb"
    if interactive:
        print("\033[2J\033[H", end="", flush=True)
    styled = interactive and "NO_COLOR" not in os.environ
    theme = load_theme(styled)
    dim, green, reset = (theme[name] for name in ("dim", "green", "reset"))
    mark = "✓" if styled else "[ok]"
    lines = ["DRIVION"]
    if interactive:
        lines = run_background(
            "Preparing Drivion", _prepare_banner, styled, stream=sys.stdout
        )
    print()
    subtitle = "Autonomous driving system"
    for line in lines:
        print(f"  {line.rstrip()}")
    print()
    print(f"  {dim}{subtitle}{reset}")
    print()
    if report is None:
        print(f"  {dim}System evaluation not run (display preview).{reset}")
    else:
        log = logging.getLogger(__name__)
        for name in (
            "configuration",
            "environment",
            "hardware",
            "arduino",
            "network",
            "camera",
            "joystick",
        ):
            result = report[name]
            status = result["status"]
            detail = result.get("error", "")
            prefix = f"{green}{mark}{reset}" if status == "ok" else "[warning]"
            message = f"{name.capitalize()}: {status}" + (
                f" — {detail}" if detail else ""
            )
            print(f"  {prefix} {message}")
            log.log(logging.INFO if status == "ok" else logging.WARNING, "%s", message)
        for camera in report["camera"].get("devices", []):
            identity = (
                f"Camera {camera['index']}: model={camera['model']} id={camera['id']}"
            )
            print(f"  {dim}{identity}{reset}")
            log.info("%s", identity)
        print(f"  {dim}Evaluation saved to system/info.toml{reset}")
    print(f"\n  {dim}Driving functionality is not implemented yet.{reset}\n")
