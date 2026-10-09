"""Exercise flashing and serial verification without touching real hardware."""

import copy
import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import tomllib

from car.system.arduino.firmware import artifact_checksums
from car.system.arduino.flash import FlashError, flash_firmware, query_firmware
from car.system.information.update import publish

ROOT = Path(__file__).resolve().parents[3] / "car"
MODULE = "car.system.arduino.flash"
IDENTITY = {
    "firmware_name": "demo",
    "firmware_version": "1.2.0",
    "protocol_version": 1,
    "git_commit": "abc123",
    "source_dirty": False,
}
REPORT = {
    "status": "ok",
    "selection": {"status": "selected", "address": "/dev/ttyUSB0"},
    "ports": [
        {
            "identification": "unidentified",
            "matching_boards": [],
            "port": {
                "address": "/dev/ttyUSB0",
                "protocol": "serial",
                "properties": {"serialNumber": "", "vid": "0x1A86", "pid": "0x7523"},
            },
        }
    ],
}


@pytest.fixture(autouse=True)
def mock_serial_dependency():
    with patch(f"{MODULE}.load_serial", return_value=SimpleNamespace()):
        yield


@pytest.fixture
def build(tmp_path):
    root = tmp_path / "car"
    root.mkdir()
    shutil.copy(ROOT / "config.toml", root)
    (root / "system").mkdir()
    shutil.copy(ROOT / "system/pyproject.toml", root / "system")
    publish(
        root / "system/info.toml",
        {"software": {"commit": "abc123"}, "hardware": {"model": "Pi"}},
    )
    artifacts = root / "system/arduino/build/demo-test/artifacts"
    artifacts.mkdir(parents=True)
    (artifacts / "demo.ino.hex").write_text(":00000001FF\n")
    publish(
        artifacts.parent / "firmware.toml",
        {
            "firmware": IDENTITY,
            "board": {"fqbn": "arduino:avr:nano:cpu=atmega328"},
            "serial": {"baud_rate": 57600, "query_command": "INFO"},
            "artifacts": artifact_checksums(artifacts),
        },
    )
    return root, artifacts


def successful_upload(*args, **kwargs):
    return subprocess.CompletedProcess(args[0], 0, "avrdude verified\n", "details\n")


def test_upload_verify_log_and_system_info(build):
    root, artifacts = build
    with (
        patch(f"{MODULE}.confirm", return_value=True) as approval,
        patch(f"{MODULE}.discover", return_value=REPORT),
        patch(f"{MODULE}.subprocess.run", side_effect=successful_upload) as run,
        patch(f"{MODULE}.query_firmware", return_value=IDENTITY) as query,
        patch(f"{MODULE}.show_progress") as waiting,
    ):
        log_path = flash_firmware(artifacts, root)
    approval.assert_called_once()
    assert waiting.call_count == 4
    command = run.call_args.args[0]
    assert command[3] == "upload"
    assert "compile" not in command
    assert "--verify" in command
    assert command[command.index("--input-dir") + 1] == str(artifacts)
    assert (
        query.call_args.args[1]["baud_rate"] == 57600
    )  # Build snapshot, not live settings.
    log = tomllib.loads(log_path.read_text())
    assert log["flash"]["status"] == "verified"
    assert log["flash"]["stdout"] == "avrdude verified\n"
    assert log["observed"] == IDENTITY
    assert log["expected"] == IDENTITY
    assert log["artifacts"] == artifact_checksums(artifacts)
    info = tomllib.loads((root / "system/info.toml").read_text())
    assert info["software"] == {"commit": "abc123"}
    assert info["hardware"] == {"model": "Pi"}
    assert info["arduino"]["firmware_name"] == "demo"
    assert info["arduino"]["firmware_version"] == "1.2.0"
    assert info["arduino"]["firmware_status"] == "verified"
    assert info["arduino"]["firmware_log"] == str(log_path)


def test_refusal_does_not_upload_log_or_change_info(build):
    root, artifacts = build
    before = (root / "system/info.toml").read_text()
    with (
        patch(f"{MODULE}.confirm", return_value=False),
        patch(f"{MODULE}.discover", return_value=REPORT),
        patch(f"{MODULE}.subprocess.run") as upload,
    ):
        assert flash_firmware(artifacts, root) is None
    upload.assert_not_called()
    assert not (root / "system/arduino/logs").exists()
    assert (root / "system/info.toml").read_text() == before


def test_modified_artifacts_rejected_before_confirmation(build):
    root, artifacts = build
    (artifacts / "demo.ino.hex").write_text("changed")
    with (
        patch(f"{MODULE}.confirm") as approval,
        pytest.raises(ValueError, match="changed since compilation"),
    ):
        flash_firmware(artifacts, root)
    approval.assert_not_called()


@pytest.mark.parametrize(
    "failure",
    [
        subprocess.CalledProcessError(1, ["upload"], "attempt", "avrdude failure"),
        subprocess.TimeoutExpired(["upload"], 120, output=b"partial"),
        KeyboardInterrupt(),
    ],
)
def test_failed_upload_is_logged_and_not_queried(build, failure):
    root, artifacts = build
    with (
        patch(f"{MODULE}.confirm", return_value=True),
        patch(f"{MODULE}.discover", return_value=REPORT),
        patch(f"{MODULE}.subprocess.run", side_effect=failure),
        patch(f"{MODULE}.query_firmware") as query,
        pytest.raises(
            KeyboardInterrupt if isinstance(failure, KeyboardInterrupt) else FlashError
        ),
    ):
        flash_firmware(artifacts, root)
    query.assert_not_called()
    log = tomllib.loads(next((root / "system/arduino/logs").glob("*.toml")).read_text())
    assert log["flash"]["upload_status"] == "failed"
    assert "error" in log["flash"]
    info = tomllib.loads((root / "system/info.toml").read_text())["arduino"]
    assert info["firmware_upload_status"] == "failed"
    assert "firmware_version" not in info


def test_query_timeout_is_not_claimed_as_verified(build):
    root, artifacts = build
    with (
        patch(f"{MODULE}.confirm", return_value=True),
        patch(f"{MODULE}.discover", return_value=REPORT),
        patch(f"{MODULE}.subprocess.run", side_effect=successful_upload),
        patch(
            f"{MODULE}.query_firmware", side_effect=TimeoutError("no firmware reply")
        ),
        pytest.raises(FlashError) as error,
    ):
        flash_firmware(artifacts, root)
    log = tomllib.loads(error.value.log_path.read_text())
    assert log["flash"]["upload_status"] == "ok"
    assert log["flash"]["verification_status"] == "failed"
    info = tomllib.loads((root / "system/info.toml").read_text())["arduino"]
    assert info["firmware_status"] == "failed"
    assert "firmware_name" not in info


def test_wrong_identity_records_observed_not_expected(build):
    root, artifacts = build
    observed = {**IDENTITY, "firmware_version": "0.9.0"}
    with (
        patch(f"{MODULE}.confirm", return_value=True),
        patch(f"{MODULE}.discover", return_value=REPORT),
        patch(f"{MODULE}.subprocess.run", side_effect=successful_upload),
        patch(f"{MODULE}.query_firmware", return_value=observed),
        pytest.raises(FlashError) as error,
    ):
        flash_firmware(artifacts, root)
    assert (
        tomllib.loads(error.value.log_path.read_text())["flash"]["verification_status"]
        == "mismatch"
    )
    info = tomllib.loads((root / "system/info.toml").read_text())["arduino"]
    assert info["firmware_version"] == "0.9.0"
    assert info["firmware_status"] == "mismatch"


@pytest.mark.parametrize("selection", [{"status": "ambiguous"}, {"status": "none"}])
def test_missing_unique_target_is_rejected(build, selection):
    root, artifacts = build
    with (
        patch(f"{MODULE}.discover", return_value={**REPORT, "selection": selection}),
        patch(f"{MODULE}.confirm") as approval,
        pytest.raises(ValueError, match="No unique target"),
    ):
        flash_firmware(artifacts, root)
    approval.assert_not_called()


def test_target_change_after_confirmation_prevents_upload(build):
    root, artifacts = build
    replacement = copy.deepcopy(REPORT)
    replacement["ports"][0]["port"]["properties"]["serialNumber"] = "replacement"
    with (
        patch(f"{MODULE}.confirm", return_value=True),
        patch(f"{MODULE}.discover", side_effect=[REPORT, replacement]),
        patch(f"{MODULE}.subprocess.run") as upload,
        pytest.raises(FlashError, match="target changed"),
    ):
        flash_firmware(artifacts, root)
    upload.assert_not_called()


def test_mismatching_board_candidate_prevents_confirmation(build):
    root, artifacts = build
    report = copy.deepcopy(REPORT)
    report["ports"][0]["matching_boards"] = [{"fqbn": "arduino:avr:uno"}]
    with (
        patch(f"{MODULE}.discover", return_value=report),
        patch(f"{MODULE}.confirm") as approval,
        pytest.raises(ValueError, match="do not match"),
    ):
        flash_firmware(artifacts, root)
    approval.assert_not_called()


def test_missing_manifest_is_not_a_flashable_build(build):
    root, artifacts = build
    (artifacts.parent / "firmware.toml").unlink()
    with patch(f"{MODULE}.confirm") as approval, pytest.raises(FileNotFoundError):
        flash_firmware(artifacts, root)
    approval.assert_not_called()


def test_missing_serial_dependency_prevents_upload(build):
    root, artifacts = build
    with (
        patch(f"{MODULE}.load_serial", side_effect=RuntimeError("pyserial missing")),
        patch(f"{MODULE}.confirm") as approval,
        patch(f"{MODULE}.subprocess.run") as upload,
        pytest.raises(RuntimeError, match="pyserial missing"),
    ):
        flash_firmware(artifacts, root)
    upload.assert_not_called()
    approval.assert_not_called()


def serial_settings():
    with (ROOT / "config.toml").open("rb") as stream:
        settings = tomllib.load(stream)["firmware_flash"]
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
