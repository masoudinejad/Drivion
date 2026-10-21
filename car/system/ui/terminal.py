"""Shared keyboard capture and terminal restoration for live terminal views."""

import os
import select
import termios
import tty
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TextIO


@dataclass(frozen=True)
class TerminalInput:
    """A controlling terminal pair; keyboard polling does not own the display."""

    reader: TextIO
    stream: TextIO

    def key(self, timeout: float) -> str | None:
        """Wait at most timeout seconds; None means no key is ready.

        Cancellation and closed input are errors, not confirmation. Read from
        the descriptor directly so text buffering cannot hide pending keystrokes
        from select on the next iteration.
        """
        ready, _, _ = select.select([self.reader], [], [], timeout)
        if not ready:
            return None
        value = os.read(self.reader.fileno(), 1)
        if not value:
            raise RuntimeError("Terminal input closed")
        if value == b"\x03":
            raise KeyboardInterrupt
        return value.decode("ascii", errors="replace")


@contextmanager
def terminal_input():
    """Use single-key input and restore the previous terminal mode on every exit.

    Display ownership stays with the caller's DriveMonitor or management screen.
    Both descriptors close even if display initialization or input polling fails.
    """
    if os.environ.get("TERM") == "dumb":
        raise RuntimeError("Live controls require an interactive ANSI terminal.")
    with (
        open("/dev/tty", encoding="utf-8") as reader,
        open("/dev/tty", "w", encoding="utf-8", buffering=1) as stream,
    ):
        saved = termios.tcgetattr(reader.fileno())
        try:
            tty.setcbreak(reader.fileno())
            yield TerminalInput(reader, stream)
        finally:
            termios.tcsetattr(reader.fileno(), termios.TCSADRAIN, saved)
