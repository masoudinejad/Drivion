"""Compact terminal startup display for the driving entry point."""

import os
import shutil
import sys


def show_startup():
    """Show startup results, using plain text when output is redirected."""
    interactive = sys.stdout.isatty() and os.environ.get("TERM") != "dumb"
    if interactive:
        print("\033[2J\033[H", end="", flush=True)
    styled = interactive and "NO_COLOR" not in os.environ
    bold, dim, cyan, green, gray, reset = (
        ("\033[1m", "\033[2m", "\033[36m", "\033[32m", "\033[90m", "\033[0m")
        if styled
        else ("", "", "", "", "", "")
    )
    mark = "✓" if styled else "[ok]"
    lines = ["DRIVION"]
    if interactive:
        # Load car dependencies only after drive.py enters its Python environment.
        from art import text2art

        banner = text2art("DRIVION", font="small", space=2).rstrip().splitlines()
        if max(map(len, banner)) + 2 <= shutil.get_terminal_size().columns:
            lines = banner
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
