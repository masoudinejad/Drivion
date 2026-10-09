"""Test bounded serial identity reads independently of the upload workflow."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from car.system.arduino.device.serial_protocol import query_firmware
from car.system.arduino.settings import tool_settings

ROOT = Path(__file__).resolve().parents[3] / "car"
MODULE = "car.system.arduino.device.serial_protocol"
IDENTITY = {
    "firmware_name": "demo",
    "firmware_version": "1.2.0",
    "protocol_version": 1,
    "git_commit": "abc123",
    "source_dirty": False,
}


def serial_settings():
    settings = tool_settings(ROOT, "flash")
    return {**settings, "boot_wait_seconds": 0}


def serial_mock(chunks):
    connection = MagicMock()
    connection.__enter__.return_value = connection
    connection.write.side_effect = lambda command: len(command)
    connection.read_until.side_effect = chunks
    return SimpleNamespace(Serial=MagicMock(return_value=connection)), connection


def test_query_handles_partial_lines_and_chatter():
    encoded = json.dumps(IDENTITY).encode() + b"\n"
    serial, connection = serial_mock([b"Ready\n", encoded[:20], encoded[20:]])
    trace = {}
    with patch(f"{MODULE}.load_serial", return_value=serial):
        assert query_firmware("/dev/ttyUSB0", serial_settings(), trace) == IDENTITY
    connection.write.assert_called_once_with(b"INFO\n")
    assert len(trace["responses"]) == 3
    assert serial.Serial.call_args.kwargs["exclusive"] is True


def test_query_bounds_response_size():
    serial, _ = serial_mock([b"x" * 1025])
    with (
        patch(f"{MODULE}.load_serial", return_value=serial),
        pytest.raises(ValueError, match="response budget"),
    ):
        query_firmware("/dev/ttyUSB0", serial_settings(), {})


def test_query_deadline_and_invalid_identity():
    serial, _ = serial_mock([b""])
    with (
        patch(f"{MODULE}.time.monotonic", side_effect=[0, 0, 0, 6]),
        patch(f"{MODULE}.load_serial", return_value=serial),
        pytest.raises(TimeoutError),
    ):
        query_firmware("/dev/ttyUSB0", serial_settings(), {})
    serial, _ = serial_mock([b'{"firmware_version":"1"}\n'])
    with (
        patch(f"{MODULE}.load_serial", return_value=serial),
        pytest.raises(ValueError, match="identity response"),
    ):
        query_firmware("/dev/ttyUSB0", serial_settings(), {})
