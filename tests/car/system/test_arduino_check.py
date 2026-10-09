"""Check running firmware without compiling, uploading or assuming a version."""

import copy
from pathlib import Path
from unittest.mock import patch

import pytest
import tomllib

from car.system.arduino.device.check import check_firmware, format_summary, main
from car.system.arduino.device.discovery import retain_firmware_info
from car.system.arduino.settings import tool_settings
from car.system.information.update import publish

ROOT = Path(__file__).resolve().parents[3] / "car"
MODULE = "car.system.arduino.device.check"
IDENTITY = {
    "firmware_name": "independent-firmware",
    "firmware_version": "2.3.0",
    "protocol_version": 1,
    "git_commit": "abc123",
    "source_dirty": True,
}
PORT = {
    "address": "/dev/ttyUSB0",
    "protocol": "serial",
    "properties": {
        "serialNumber": "usb-id",
        "vid": "0x1234",
        "pid": "0x5678",
    },
}
REPORT = {
    "status": "ok",
    "selection": {"status": "selected", "address": "/dev/ttyUSB0"},
    "ports": [{"port": PORT, "matching_boards": []}],
}


@pytest.fixture
def car_root(car_tree):
    root = car_tree
    publish(
        root / "system/info.toml",
        {
            "software": {"commit": "pi-software"},
            "hardware": {"model": "Pi"},
            "arduino": {
                "address": PORT["address"],
                **PORT["properties"],
                "firmware_name": "old",
                "firmware_version": "0.1",
                "firmware_status": "verified",
                "firmware_log": "/previous-flash.toml",
                "firmware_upload_status": "ok",
            },
        },
    )
    return root


@pytest.fixture(autouse=True)
def dependencies():
    with (
        patch(f"{MODULE}.load_serial"),
        patch(f"{MODULE}.discover", return_value=REPORT),
        patch(f"{MODULE}.confirm", return_value=True),
    ):
        yield


def saved_info(root):
    return tomllib.loads((root / "system/info.toml").read_text())


def test_reported_identity_and_preserved_flash_provenance(car_root):
    with (
        patch(f"{MODULE}.query_firmware", return_value=IDENTITY) as query,
        patch(f"{MODULE}.show_progress") as waiting,
        patch(f"{MODULE}.discover", return_value=REPORT) as scans,
    ):
        result = check_firmware(car_root)
    assert result["status"] == "ok"
    assert result["firmware"] == IDENTITY
    assert waiting.call_count == 3
    assert scans.call_count == 2
    assert all(call.kwargs["detailed"] is False for call in scans.call_args_list)
    assert (
        scans.call_args_list[0].kwargs["context"]
        is scans.call_args_list[1].kwargs["context"]
    )
    assert query.call_args.args[0] == PORT["address"]
    assert query.call_args.args[1] == tool_settings(car_root, "flash")
    info = saved_info(car_root)
    assert info["software"] == {"commit": "pi-software"}
    assert info["hardware"] == {"model": "Pi"}
    assert info["arduino"]["firmware_name"] == IDENTITY["firmware_name"]
    assert info["arduino"]["firmware_version"] == IDENTITY["firmware_version"]
    assert info["arduino"]["firmware_status"] == "reported"
    assert info["arduino"]["firmware_checked_at"] == result["checked_at"]
    assert info["arduino"]["firmware_log"] == "/previous-flash.toml"
    assert info["arduino"]["firmware_upload_status"] == "ok"
    assert "query" not in info["arduino"]
    assert (
        retain_firmware_info(
            {"address": PORT["address"], **PORT["properties"]}, info["arduino"]
        )["firmware_status"]
        == "last_reported"
    )


def test_refusal_does_not_query_or_change_info(car_root):
    before = saved_info(car_root)
    with (
        patch(f"{MODULE}.confirm", return_value=False),
        patch(f"{MODULE}.query_firmware") as query,
    ):
        assert check_firmware(car_root) is None
    query.assert_not_called()
    assert saved_info(car_root) == before


@pytest.mark.parametrize(
    "failure",
    [TimeoutError("no reply"), OSError("port busy"), ValueError("malformed identity")],
)
def test_failed_query_clears_stale_identity_not_flash_history(car_root, failure):
    with patch(f"{MODULE}.query_firmware", side_effect=failure):
        result = check_firmware(car_root)
    assert result["status"] == "error"
    assert str(failure) in result["error"]
    info = saved_info(car_root)["arduino"]
    assert info["firmware_status"] == "error"
    assert "firmware_name" not in info
    assert "firmware_version" not in info
    assert info["firmware_log"] == "/previous-flash.toml"
    assert info["firmware_upload_status"] == "ok"


def test_invalid_reply_is_not_published_as_identity(car_root):
    with patch(f"{MODULE}.query_firmware", return_value={"firmware_name": "guessed"}):
        result = check_firmware(car_root)
    assert result["status"] == "error"
    assert "firmware_name" not in saved_info(car_root)["arduino"]


def test_missing_unique_target_never_opens_serial(car_root):
    with (
        patch(
            f"{MODULE}.discover", return_value={"selection": {"status": "ambiguous"}}
        ),
        patch(f"{MODULE}.query_firmware") as query,
        pytest.raises(ValueError, match="No unique target"),
    ):
        check_firmware(car_root)
    query.assert_not_called()


def test_changed_device_after_approval_does_not_query(car_root):
    replacement = copy.deepcopy(REPORT)
    replacement["ports"][0]["port"]["properties"]["serialNumber"] = "replacement"
    before = saved_info(car_root)
    with (
        patch(f"{MODULE}.discover", side_effect=[REPORT, replacement]),
        patch(f"{MODULE}.query_firmware") as query,
        pytest.raises(ValueError, match="changed after approval"),
    ):
        check_firmware(car_root)
    query.assert_not_called()
    assert saved_info(car_root) == before


def test_interrupted_query_invalidates_old_identity(car_root):
    with (
        patch(f"{MODULE}.query_firmware", side_effect=KeyboardInterrupt),
        pytest.raises(KeyboardInterrupt),
    ):
        check_firmware(car_root)
    info = saved_info(car_root)["arduino"]
    assert info["firmware_status"] == "interrupted"
    assert "firmware_version" not in info


def test_other_ports_are_preserved(car_root):
    second = {
        "address": "/dev/ttyUSB1",
        "protocol": "serial",
        "properties": {"serialNumber": "second"},
    }
    report = copy.deepcopy(REPORT)
    report["ports"].append({"port": second, "matching_boards": []})
    old = saved_info(car_root)
    old["arduino"] = {
        "ports": [
            old["arduino"],
            {
                "address": second["address"],
                **second["properties"],
                "firmware_version": "keep",
            },
        ]
    }
    publish(car_root / "system/info.toml", old)
    with (
        patch(f"{MODULE}.discover", return_value=report),
        patch(f"{MODULE}.query_firmware", return_value=IDENTITY),
    ):
        check_firmware(car_root)
    ports = saved_info(car_root)["arduino"]["ports"]
    assert ports[0]["firmware_version"] == IDENTITY["firmware_version"]
    assert ports[1]["firmware_version"] == "keep"


def test_summary_and_cli_statuses(capsys):
    report = {
        "status": "ok",
        "address": PORT["address"],
        "firmware": IDENTITY,
        "checked_at": "now",
        "query": {"responses": ["verbose-only"]},
    }
    assert "Version: 2.3.0" in format_summary(report)
    assert "verbose-only" not in format_summary(report)
    with patch(f"{MODULE}.check_firmware", return_value=report):
        assert main([]) == 0
    assert "verbose-only" not in capsys.readouterr().out
    with patch(f"{MODULE}.check_firmware", return_value=None):
        assert main([]) == 1
    with patch(f"{MODULE}.check_firmware", side_effect=KeyboardInterrupt):
        assert main([]) == 130
