"""Reusable terminal feedback while a foreground or background task runs."""

import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from itertools import cycle

if __package__:
    from .theme import load_theme
else:
    from theme import load_theme


@contextmanager
def show_progress(message, *, stream=None):
    """Animate until the enclosed work finishes; propagate failures unchanged.

    Use stderr by default so command output remains usable. Redirected output
    gets one plain status line. The caller owns and waits for any background job.
    """
    if not message or any(ord(char) < 32 or ord(char) == 127 for char in message):
        raise ValueError("Progress messages must be non-empty and single-line")
    stream = sys.stderr if stream is None else stream
    interactive = stream.isatty() and os.environ.get("TERM") != "dumb"
    styled = interactive and "NO_COLOR" not in os.environ
    theme = load_theme(styled)
    cyan, dim, reset = (theme[name] for name in ("cyan", "dim", "reset"))
    stopped = threading.Event()

    def animate():
        for frame in cycle("⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"):
            stream.write(f"\r\033[2K  {cyan}{frame}{reset} {dim}{message}{reset}")
            stream.flush()
            if stopped.wait(0.1):
                break

    worker = None
    if interactive:
        worker = threading.Thread(target=animate, daemon=True)
        worker.start()
    else:
        print(f"  {message}…", file=stream, flush=True)
    try:
        yield
    finally:
        stopped.set()
        if worker is not None:
            worker.join()
            stream.write("\r\033[2K")
            stream.flush()


def run_background(message, operation, *args, stream=None, **kwargs):
    """Run an operation in a worker thread with progress until it completes.

    Return the operation's result or propagate its exception. Operations must
    not write to the progress stream while the animation is active.
    """
    with (
        show_progress(message, stream=stream),
        ThreadPoolExecutor(max_workers=1) as executor,
    ):
        return executor.submit(operation, *args, **kwargs).result()


def main():
    """Run a command with progress feedback, preserving its output and status."""
    import argparse
    import subprocess

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--message", required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command
    if command[:1] == ["--"]:
        command = command[1:]
    if not command:
        parser.error("provide a command after --")
    try:
        with show_progress(args.message):
            return subprocess.call(command)
    except (OSError, ValueError) as error:
        parser.exit(2, f"progress: {error}\n")


if __name__ == "__main__":
    sys.exit(main())
