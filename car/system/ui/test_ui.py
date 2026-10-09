"""Interactive, non-destructive smoke test of every UI element on the Pi."""

import os
import subprocess
import sys
import time
from pathlib import Path

# Allow running this single file directly from any working directory.
UI = Path(__file__).resolve().parent
sys.path.insert(0, str(UI.parents[1]))

from system.ui.progress import run_background
from system.ui.startup import show_startup


def exercise(script, *args):
    """Show a UI element and report its answer and status after restoration."""
    result = subprocess.run(
        ["bash", str(UI / script), *args],
        capture_output=script != "progress.sh",
        text=True,
        check=False,
    )
    print(
        f"Answer: {(result.stdout or '').strip() or '(none)'}; status: {result.returncode}"
    )
    if result.returncode == 130:
        raise KeyboardInterrupt
    if result.returncode not in (0, 1, 3):
        raise RuntimeError((result.stderr or "").strip() or f"{script} failed")


def main():
    """Walk through banner, progress, selection, confirmation, and typed input."""
    if (
        not sys.stdin.isatty()
        or not sys.stdout.isatty()
        or os.environ.get("TERM") == "dumb"
    ):
        print(
            "Run this test in an interactive terminal (SSH is supported).",
            file=sys.stderr,
        )
        return 2
    show_startup()
    input("Press Enter to test background progress… ")
    # A deliberate demo task makes the animation visible without touching hardware.
    run_background("Demonstration background task", time.sleep, 2)
    exercise("progress.sh", "--message", "Command progress", "--", "sleep", "2")
    exercise(
        "menu.sh",
        "--title",
        "Test arrows, Enter, or Escape",
        "--description",
        "First demonstration action",
        "--description",
        "Second demonstration action",
        "--",
        "First",
        "Second",
    )
    exercise("confirm.sh", "--question", "Does the confirmation look correct?")
    for kind, example in (
        ("text", "hello"),
        ("integer", "30"),
        ("number", "0.5"),
        ("boolean", "yes"),
    ):
        exercise(
            "prompt.sh",
            "--question",
            f"Enter {example}, try invalid input, or Escape",
            "--type",
            kind,
        )
    print("UI walkthrough complete. Check that the terminal and cursor are restored.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nUI walkthrough cancelled.", file=sys.stderr)
        sys.exit(130)
    except (OSError, RuntimeError, ValueError) as error:
        print(f"UI walkthrough failed: {error}", file=sys.stderr)
        sys.exit(2)
