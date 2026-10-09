"""Exercise the Bash menu through a real pseudo-terminal."""

import fcntl
import os
import pty
import re
import select
import signal
import struct
import termios
import time
import unittest
from pathlib import Path

MENU = Path(__file__).resolve().parents[4] / "car/system/ui/menu.sh"


class MenuTests(unittest.TestCase):
    def run_menu(self, keys, options='"One" "Two"', sourced=False, managed=False):
        invocation = "drivion_menu" if sourced else 'bash "$MENU"'
        setup = 'source "$MENU"; set -euo pipefail;' if sourced else ""
        script = (
            f'{setup} trap ":" INT; before=$(stty -g); '
            f"if result=$({invocation} --title Test {options}); then status=0; "
            'else status=$?; fi; after=$(stty -g); printf "BEFORE=%s AFTER=%s\\n" "$before" "$after"; '
            'printf "RESULT=%s STATUS=%s RESTORED=%s\\n" "$result" "$status" '
            '"$([ "$before" = "$after" ] && echo yes || echo no)"'
        )
        pid, terminal = pty.fork()
        if pid == 0:
            fcntl.ioctl(0, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 80, 0, 0))
            os.environ["TERM"] = "xterm-256color"
            os.environ.pop("NO_COLOR", None)
            os.environ["MENU"] = str(MENU)
            if managed:
                os.environ["DRIVION_UI_SCREEN_ACTIVE"] = "1"
            else:
                os.environ.pop("DRIVION_UI_SCREEN_ACTIVE", None)
            os.execv("/bin/bash", ["bash", "-c", script])
        output = b""
        sent = False
        deadline = time.monotonic() + 5
        try:
            while time.monotonic() < deadline:
                if not select.select([terminal], [], [], 0.1)[0]:
                    continue
                try:
                    chunk = os.read(terminal, 65536)
                except OSError:
                    break
                if not chunk:
                    break
                output += chunk
                if not sent and b"[Enter] Select" in output:
                    os.write(terminal, keys)
                    sent = True
            else:
                os.kill(pid, signal.SIGKILL)
                self.fail("Menu timed out")
        finally:
            os.close(terminal)
            os.waitpid(pid, 0)
        self.assertIn(b"Back", output)
        states = re.search(rb"BEFORE=(\S+) AFTER=(\S+)", output)
        self.assertIsNotNone(states)
        before, after = states.groups()

        # macOS sets the transient PENDIN flag when canonical input is restored.
        def normalize(state):
            return re.sub(
                rb"lflag=([0-9a-f]+)",
                lambda match: (
                    b"lflag=%x"
                    % (int(match.group(1), 16) & ~getattr(termios, "PENDIN", 0))
                ),
                state,
            )

        self.assertEqual(normalize(before), normalize(after))
        return output

    def test_second_option(self):
        self.assertIn(b"RESULT=2 STATUS=0", self.run_menu(b"\x1b[B\r"))

    def test_back_with_wrap(self):
        self.assertIn(b"RESULT=0 STATUS=0", self.run_menu(b"\x1b[A\r"))

    def test_shared_screen_and_back_style(self):
        output = self.run_menu(b"\x1b[A\r", managed=True)
        self.assertIn(b"RESULT=0 STATUS=0", output)
        self.assertNotIn(b"\x1b[?1049h", output)
        self.assertNotIn(b"\x1b[?1049l", output)
        self.assertNotIn(b"\x1b[33m", output)
        self.assertIn("\x1b[36m▸ Back".encode(), output)

    def test_escape(self):
        self.assertIn(b"RESULT=0 STATUS=0", self.run_menu(b"\x1b"))

    def test_sourced_function(self):
        self.assertIn(b"RESULT=1 STATUS=0", self.run_menu(b"\r", sourced=True))

    def test_empty_options(self):
        self.assertIn(b"RESULT=0 STATUS=0", self.run_menu(b"\r", options=""))

    def test_long_menu(self):
        options = " ".join(f'"Option {number}"' for number in range(30))
        self.assertIn(
            b"RESULT=21 STATUS=0", self.run_menu(b"\x1b[B" * 20 + b"\r", options)
        )

    def test_cancel(self):
        self.assertIn(b"STATUS=130", self.run_menu(b"\x03"))


if __name__ == "__main__":
    unittest.main()
