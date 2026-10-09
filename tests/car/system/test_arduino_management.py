"""Verify user-selected Arduino addresses pass through the config modifier."""

import copy
from pathlib import Path
from unittest.mock import patch

import pytest
import tomllib

from car.system.arduino.management import menu as management
from car.system.management.application import default_items

DEVICE = {
    "port": {
        "address": "/dev/ttyUSB0",
        "properties": {"vid": "0x1A86", "pid": "0x7523"},
    },
    "matching_boards": [],
}


@pytest.fixture
def car_root(tmp_path):
    source = Path(__file__).resolve().parents[3] / "car/config.toml"
    (tmp_path / "config.toml").write_text(source.read_text())
    return tmp_path


def run_identification(root, reports, selection=0):
    pages = []
    with patch.object(management, "run_background", side_effect=reports):
        management.identify_device(
            root,
            select=lambda title, labels: selection,
            display=lambda *args: pages.append(args),
        )
    return pages


def test_menu_registers_arduino_after_system_info():
    assert [item.label for item in default_items()][:2] == ["System Info", "Arduino"]


def test_select_updates_only_address_preserving_comments(car_root):
    path = car_root / "config.toml"
    before = path.read_text()
    report = {"status": "ok", "ports": [copy.deepcopy(DEVICE)]}
    pages = run_identification(car_root, [report, report])
    assert path.read_text() == before.replace(
        'address = "auto"', 'address = "/dev/ttyUSB0"'
    )
    assert "Unidentified" not in pages[0][0]
    assert "/dev/ttyUSB0" in pages[0][1]


def test_multiple_devices_save_user_selection(car_root):
    other = copy.deepcopy(DEVICE)
    other["port"]["address"] = "/dev/ttyACM0"
    report = {"status": "partial", "ports": [DEVICE, other]}
    run_identification(car_root, [report, report], selection=1)
    config = tomllib.loads((car_root / "config.toml").read_text())
    assert config["arduino"]["address"] == "/dev/ttyACM0"


@pytest.mark.parametrize(
    "report",
    [
        {"status": "ok", "ports": []},
        {"status": "error", "error": "CLI missing", "ports": []},
    ],
)
def test_empty_or_failed_scan_does_not_write(car_root, report):
    before = (car_root / "config.toml").read_bytes()
    assert run_identification(car_root, [report])
    assert (car_root / "config.toml").read_bytes() == before


def test_back_does_not_write(car_root):
    before = (car_root / "config.toml").read_bytes()
    assert not run_identification(car_root, [{"ports": [DEVICE]}], selection=None)
    assert (car_root / "config.toml").read_bytes() == before


@pytest.mark.parametrize(
    "changed",
    [[], [{"port": {"address": "/dev/ttyUSB0", "properties": {"vid": "changed"}}}]],
)
def test_disconnected_or_changed_device_does_not_write(car_root, changed):
    before = (car_root / "config.toml").read_bytes()
    with pytest.raises(RuntimeError, match="disconnected or changed"):
        run_identification(car_root, [{"ports": [DEVICE]}, {"ports": changed}])
    assert (car_root / "config.toml").read_bytes() == before


def test_submenu_returns_and_dispatches(car_root):
    choices = iter([0, None])
    with patch.object(management, "identify_device") as identify:
        management.arduino_menu(car_root, select=lambda *args: next(choices))
    identify.assert_called_once_with(car_root)


def test_empty_address_can_be_selected(car_root):
    from car.src.config import update_config
    from car.system.configuration import arduino_settings

    path = car_root / "config.toml"
    update_config("arduino.address", "", path)
    assert arduino_settings(car_root).address == ""
    report = {"ports": [DEVICE]}
    run_identification(car_root, [report, report])
    assert arduino_settings(car_root).address == "/dev/ttyUSB0"


def test_check_firmware_menu_dispatch(car_root):
    choices = iter([2, None])
    with patch.object(management, "check_firmware_page") as action:
        management.arduino_menu(car_root, select=lambda *args: next(choices))
    action.assert_called_once_with(car_root)


@pytest.mark.parametrize("status", ["ok", "error"])
def test_firmware_check_page_uses_existing_summary(car_root, status):
    report = {"status": status}
    pages = []
    with (
        patch.object(management, "check_firmware", return_value=report) as check,
        patch.object(
            management, "format_summary", return_value=f"Summary: {status}"
        ) as summary,
    ):
        management.check_firmware_page(
            car_root, display=lambda *args: pages.append(args)
        )
    check.assert_called_once_with(car_root)
    summary.assert_called_once_with(report)
    assert pages == [("Check firmware", f"Summary: {status}")]


def test_declined_check_returns_without_page(car_root):
    with patch.object(management, "check_firmware", return_value=None):
        management.check_firmware_page(
            car_root, display=lambda *args: pytest.fail("Unexpected page")
        )


def test_check_preflight_error_is_displayed(car_root):
    pages = []
    with patch.object(
        management, "check_firmware", side_effect=ValueError("No unique target")
    ):
        management.check_firmware_page(
            car_root, display=lambda *args: pages.append(args)
        )
    assert pages == [("Firmware check failed", "No unique target")]


def test_check_cancellation_propagates(car_root):
    with (
        patch.object(management, "check_firmware", side_effect=KeyboardInterrupt),
        pytest.raises(KeyboardInterrupt),
    ):
        management.check_firmware_page(car_root)
