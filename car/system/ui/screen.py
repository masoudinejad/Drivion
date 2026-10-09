"""Own one alternate terminal screen across a complete management session."""

import os
import sys
from contextlib import contextmanager

SCREEN_ENV = "DRIVION_UI_SCREEN_ACTIVE"


@contextmanager
def terminal_screen(*, stream=None):
    """Keep child UI helpers on this screen and restore the shell on exit.

    Nested sessions share their owner's screen. Redirected and dumb terminals
    remain plain; the environment flag describes runtime ownership, not theme.
    """
    stream = sys.stdout if stream is None else stream
    if (
        os.environ.get(SCREEN_ENV) == "1"
        or not stream.isatty()
        or os.environ.get("TERM") == "dumb"
    ):
        yield
        return
    previous = os.environ.get(SCREEN_ENV)
    stream.write("\033[?1049h\033[H\033[2J")
    stream.flush()
    os.environ[SCREEN_ENV] = "1"
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(SCREEN_ENV, None)
        else:
            os.environ[SCREEN_ENV] = previous
        stream.write("\033[?25h\033[?1049l")
        stream.flush()
