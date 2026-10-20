"""Exercise shared completion feedback and numeric prompt result handling."""

import io
import subprocess
from unittest.mock import patch

import pytest

from car.system.ui.navigation import prompt_number
from car.system.ui.progress import show_success


def test_success_feedback_without_acknowledgement():
    stream = io.StringIO()
    show_success("Joystick initialized", stream=stream)
    assert stream.getvalue() == "  ✓ Joystick initialized\n"
    with pytest.raises(ValueError):
        show_success("invalid\nmessage", stream=stream)


@pytest.mark.parametrize("status,output,expected", [(0, "0.05\n", 0.05), (3, "", None)])
def test_numeric_answer_or_ignore(status, output, expected):
    with patch(
        "car.system.ui.navigation.subprocess.run",
        return_value=subprocess.CompletedProcess([], status, output, ""),
    ):
        assert prompt_number("Dead zone?") == expected


@pytest.mark.parametrize("status,error", [(130, KeyboardInterrupt), (2, RuntimeError)])
def test_numeric_prompt_propagates_cancel_or_failure(status, error):
    with (
        patch(
            "car.system.ui.navigation.subprocess.run",
            return_value=subprocess.CompletedProcess([], status, "", "failed"),
        ),
        pytest.raises(error),
    ):
        prompt_number("Dead zone?")
