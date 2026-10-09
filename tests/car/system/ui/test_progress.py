"""Verify progress cleanup, fallback output, and command status."""

import io
import os
import subprocess
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from car.system.ui.progress import run_background, show_progress
from car.system.ui.theme import STYLE_NAMES, load_theme

PROGRESS = Path(__file__).resolve().parents[4] / "car/system/ui/progress.py"


class ProgressTests(unittest.TestCase):
    def test_shared_bash_palette(self):
        script = PROGRESS.with_name("theme.sh")
        result = subprocess.run(
            [
                "bash",
                "-c",
                (
                    'source "$1"; drivion_load_theme; '
                    'printf "%s\\n" "$cyan" "$amber" "$red" "$green" "$gray" '
                    '"$bold" "$dim" "$reset"'
                ),
                "bash",
                str(script),
            ],
            capture_output=True,
            text=True,
            check=True,
            env={key: value for key, value in os.environ.items() if key != "NO_COLOR"},
        )
        theme = load_theme()
        self.assertEqual(
            result.stdout.splitlines(), [theme[name] for name in STYLE_NAMES]
        )
        self.assertTrue(all(value == "" for value in load_theme(False).values()))

    def test_redirected_and_failure(self):
        stream = io.StringIO()
        with (
            self.assertRaisesRegex(RuntimeError, "failed"),
            show_progress("Working", stream=stream),
        ):
            raise RuntimeError("failed")
        self.assertEqual(stream.getvalue(), "  Working…\n")

    def test_interactive_cleanup(self):
        stream = io.StringIO()
        stream.isatty = lambda: True
        with (
            patch.dict(os.environ, {"TERM": "xterm", "NO_COLOR": "1"}),
            show_progress("Working", stream=stream),
        ):
            pass
        self.assertTrue(stream.getvalue().endswith("\r\033[2K"))
        self.assertNotIn("\033[36m", stream.getvalue())

    def test_background_result_and_failure(self):
        stream = io.StringIO()
        caller = threading.get_ident()
        worker = run_background("Working", threading.get_ident, stream=stream)
        self.assertNotEqual(caller, worker)
        self.assertEqual(run_background("Working", pow, 2, 3, stream=stream), 8)
        with self.assertRaises(ZeroDivisionError):
            run_background("Working", lambda: 1 / 0, stream=stream)

    def test_command_status_and_output(self):
        result = subprocess.run(
            [
                sys.executable,
                str(PROGRESS),
                "--message",
                "Working",
                "--",
                sys.executable,
                "-c",
                "print('result'); raise SystemExit(7)",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 7)
        self.assertEqual(result.stdout, "result\n")
        self.assertEqual(result.stderr, "  Working…\n")
