"""Verify confirmation maps validated answers without swallowing terminal errors."""

import subprocess
import unittest
from pathlib import Path

CONFIRM = Path(__file__).resolve().parents[4] / "car/system/ui/confirm.sh"


class ConfirmTests(unittest.TestCase):
    def test_prompt_results(self):
        for selection, status, expected in [
            ("true", 0, 0),
            ("false", 0, 1),
            ("", 3, 1),
            (0, 130, 130),
            (0, 2, 2),
        ]:
            with self.subTest(selection=selection, status=status):
                result = subprocess.run(
                    [
                        "bash",
                        "-c",
                        (
                            'source "$1"; drivion_prompt() { printf "%s" "$2" >&2; '
                            f'printf "{selection}"; return {status}; '
                            '}; drivion_confirm --question "Continue?"'
                        ),
                        "bash",
                        str(CONFIRM),
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(result.returncode, expected)
                self.assertEqual(result.stdout, "")
                self.assertEqual(result.stderr, "Continue? (yes/no or y/n)")
