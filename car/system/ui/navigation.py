"""Python adapters for management menus and read-only terminal pages."""

import os
import subprocess
from pathlib import Path

from .theme import load_theme, menu_descriptions


def confirm(question):
    """Use the shared confirmation UI; never treat UI failure as approval."""
    result = subprocess.run(
        ["bash", str(Path(__file__).with_name("confirm.sh")), "--question", question],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 130:
        raise KeyboardInterrupt
    if result.returncode not in (0, 1):
        raise RuntimeError(result.stderr.strip() or "Unable to ask for confirmation")
    return result.returncode == 0


def select_item(title, labels):
    """Return a zero-based selection, or None for Back; propagate cancellation."""
    descriptions = menu_descriptions(title, labels)
    description_args = [
        value
        for description in descriptions
        for value in ("--description", description)
    ]
    result = subprocess.run(
        [
            "bash",
            str(Path(__file__).with_name("menu.sh")),
            "--title",
            title,
            *description_args,
            "--",
            *labels,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 130:
        raise KeyboardInterrupt
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "Unable to open menu")
    selection = int(result.stdout.strip())
    if not 0 <= selection <= len(labels):
        raise ValueError("Menu returned an invalid selection")
    return selection - 1 if selection else None


def show_page(title, content):
    """Show a themed, scrollable terminal transcript and wait for Enter to return.

    Use the controlling terminal, matching the Bash UI even when stdout is
    redirected. Normal terminal scrollback keeps long information accessible.
    """
    with (
        open("/dev/tty", encoding="utf-8") as reader,
        open("/dev/tty", "w", encoding="utf-8", buffering=1) as terminal,
    ):
        theme = load_theme("NO_COLOR" not in os.environ)
        terminal.write(f"\n{theme['cyan']}{theme['bold']}{title}{theme['reset']}\n\n")
        terminal.write(content + "\n\n")
        terminal.write(f"{theme['dim']}Press Enter to go back.{theme['reset']} ")
        terminal.flush()
        if not reader.readline():
            raise RuntimeError("Terminal input closed")
