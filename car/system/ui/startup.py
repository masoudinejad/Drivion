"""Compact terminal startup display for the driving entry point."""

import os
import shutil
import sys

from .progress import run_background
from .theme import load_theme


def _prepare_banner():
    """Render the title after entering the car environment, fitting its width."""
    from art import text2art

    banner = text2art("DRIVION", font="small", space=2).rstrip().splitlines()
    if max(map(len, banner)) + 2 <= shutil.get_terminal_size().columns:
        return banner
    return ["DRIVION"]


def show_startup():
    """Show startup results, using plain text when output is redirected."""
    interactive = sys.stdout.isatty() and os.environ.get("TERM") != "dumb"
    if interactive:
        print("\033[2J\033[H", end="", flush=True)
    styled = interactive and "NO_COLOR" not in os.environ
    theme = load_theme(styled)
    bold, dim, cyan, green, gray, reset = (
        theme[name] for name in ("bold", "dim", "cyan", "green", "gray", "reset")
    )
    mark = "✓" if styled else "[ok]"
    lines = ["DRIVION"]
    if interactive:
        lines = run_background("Preparing Drivion", _prepare_banner, stream=sys.stdout)
    print()
    rule = "─" if interactive else "-"
    subtitle = "Autonomous driving system"
    border = rule * max(len(subtitle), *(len(line.rstrip()) for line in lines))
    print(f"  {gray}{border}{reset}")
    for line in lines:
        print(f"  {cyan}{bold}{line.rstrip()}{reset}")
    print()
    print(f"  {dim}{subtitle}{reset}")
    print(f"  {gray}{border}{reset}\n")
    print(f"  {green}{mark}{reset} Configuration loaded")
    print(f"  {green}{mark}{reset} Python environment ready")
    print(f"\n  {dim}Driving functionality is not implemented yet.{reset}\n")
