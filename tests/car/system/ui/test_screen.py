"""Verify management screen ownership and restoration across nested UI work."""

import io
import os
import unittest
from unittest.mock import patch

from car.system.ui.progress import show_progress
from car.system.ui.screen import SCREEN_ENV, terminal_screen


class ScreenTests(unittest.TestCase):
    def test_nested_progress_failure_restores_shell(self):
        stream = io.StringIO()
        stream.isatty = lambda: True
        with patch.dict(os.environ, {"TERM": "xterm"}):
            os.environ.pop(SCREEN_ENV, None)
            with (
                self.assertRaisesRegex(RuntimeError, "failed"),
                terminal_screen(stream=stream),
            ):
                self.assertEqual(os.environ[SCREEN_ENV], "1")
                with (
                    terminal_screen(stream=stream),
                    show_progress("Working", stream=stream),
                ):
                    raise RuntimeError("failed")
            self.assertNotIn(SCREEN_ENV, os.environ)
        output = stream.getvalue()
        self.assertEqual(output.count("\033[?1049h"), 1)
        self.assertEqual(output.count("\033[?1049l"), 1)
        self.assertTrue(output.endswith("\033[?25h\033[?1049l"))

    def test_redirected_output_does_not_switch_screens(self):
        stream = io.StringIO()
        with terminal_screen(stream=stream):
            stream.write("result")
        self.assertEqual(stream.getvalue(), "result")
