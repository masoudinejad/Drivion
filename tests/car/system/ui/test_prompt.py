"""Exercise the Bash prompt through a real pseudo-terminal."""

import fcntl
import os
import pty
import re
import select
import shlex
import signal
import struct
import termios
import time
import unittest
from pathlib import Path

PROMPT = Path(__file__).resolve().parents[4] / "car/system/ui/prompt.sh"


class PromptTests(unittest.TestCase):
    def run_prompt(
        self,
        keys,
        kind="text",
        sourced=False,
        question="Test",
        columns=80,
        confirm=False,
        managed=False,
    ):
        invocation = "drivion_prompt" if sourced else 'bash "$PROMPT"'
        setup = 'source "$PROMPT"; set -euo pipefail;' if sourced else ""
        question = shlex.quote(question)
        if confirm:
            invocation = 'bash "$CONFIRM"'
        script = (
            f'{setup} trap ":" INT; before=$(stty -g); '
            f"if result=$({invocation} --question {question} {'' if confirm else '--type ' + kind}); then status=0; "
            'else status=$?; fi; after=$(stty -g); printf "BEFORE=%s AFTER=%s\\n" "$before" "$after"; '
            'printf "RESULT=%s STATUS=%s RESTORED=%s\\n" "$result" "$status" '
            '"$([ "$before" = "$after" ] && echo yes || echo no)"'
        )
        pid, terminal = pty.fork()
        if pid == 0:
            fcntl.ioctl(0, termios.TIOCSWINSZ, struct.pack("HHHH", 24, columns, 0, 0))
            os.environ["TERM"] = "xterm-256color"
            os.environ["PROMPT"] = str(PROMPT)
            if managed:
                os.environ["DRIVION_UI_SCREEN_ACTIVE"] = "1"
            else:
                os.environ.pop("DRIVION_UI_SCREEN_ACTIVE", None)
            os.environ["CONFIRM"] = str(PROMPT.with_name("confirm.sh"))
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
                if not sent and b"[Esc] Ignore" in output:
                    os.write(terminal, keys)
                    sent = True
            else:
                os.kill(pid, signal.SIGKILL)
                self.fail("Prompt timed out")
        finally:
            os.close(terminal)
            os.waitpid(pid, 0)
        self.assertIn(b"Ignore", output)
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

    def test_long_confirmation_displays_complete_question(self):
        question = (
            "Check running firmware on /dev/ttyUSB0? Opening serial may reset the board. "
            "Confirm driving is stopped, motors are safe and other serial users are closed"
        )
        for columns in (40, 80, 120):
            with self.subTest(columns=columns):
                output = self.run_prompt(
                    b"yes\r", question=question, columns=columns, confirm=True
                )
                plain = re.sub(rb"\x1b\[[0-9;?]*[A-Za-z]", b"", output).decode()
                heading = plain.split("Type:", 1)[0]
                self.assertIn(question + " (yes/no or y/n)", " ".join(heading.split()))
                self.assertTrue(
                    all(len(line) <= columns for line in heading.splitlines())
                )
                self.assertIn(b"STATUS=0", output)

    def test_unbroken_question_wraps_without_losing_characters(self):
        question = "x" * 100
        output = self.run_prompt(b"hello\r", question=question, columns=40)
        plain = re.sub(rb"\x1b\[[0-9;?]*[A-Za-z]", b"", output).decode()
        heading = plain.split("Type:", 1)[0]
        self.assertEqual("".join(heading.split()), question)

    def test_text_and_editing(self):
        self.assertIn(b"RESULT=hello STATUS=0", self.run_prompt(b"hellx\x7fo\r"))

    def test_integer_retry(self):
        output = self.run_prompt(b"wrong\r-30\r", "integer")
        self.assertIn(b"Please enter an integer", output)
        self.assertIn(b"RESULT=-30 STATUS=0", output)

    def test_number_retry(self):
        output = self.run_prompt(b"NaN\r1.5e-2\r", "number")
        self.assertIn(b"Please enter a number", output)
        self.assertIn(b"RESULT=1.5e-2 STATUS=0", output)

    def test_boolean(self):
        self.assertIn(b"RESULT=true STATUS=0", self.run_prompt(b"YeS\r", "boolean"))
        self.assertIn(b"RESULT=false STATUS=0", self.run_prompt(b"no\r", "boolean"))

    def test_boolean_short_forms_and_case(self):
        for answer, expected in [
            ("y", "true"),
            ("Y", "true"),
            ("YES", "true"),
            ("n", "false"),
            ("N", "false"),
            ("NO", "false"),
        ]:
            with self.subTest(answer=answer):
                output = self.run_prompt((answer + "\r").encode(), "boolean")
                self.assertIn(f"RESULT={expected} STATUS=0".encode(), output)

    def test_blank_retry(self):
        output = self.run_prompt(b"\rhello\r")
        self.assertIn(b"Please enter non-empty text", output)
        self.assertIn(b"RESULT=hello STATUS=0", output)

    def test_shared_screen_cancellation(self):
        output = self.run_prompt(b"\x03", managed=True)
        self.assertIn(b"RESULT= STATUS=130", output)
        self.assertNotIn(b"\x1b[?1049h", output)
        self.assertNotIn(b"\x1b[?1049l", output)

    def test_ignore(self):
        self.assertIn(b"RESULT= STATUS=3", self.run_prompt(b"\x1b"))

    def test_cancel(self):
        self.assertIn(b"RESULT= STATUS=130", self.run_prompt(b"\x03"))

    def test_sourced_function(self):
        self.assertIn(
            b"RESULT=hello STATUS=0", self.run_prompt(b"hello\r", sourced=True)
        )

    def test_clear_and_arrow(self):
        self.assertIn(
            b"RESULT=42 STATUS=0", self.run_prompt(b"old\x15\x1b[B42\r", "integer")
        )


if __name__ == "__main__":
    unittest.main()
