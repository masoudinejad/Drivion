"""Verify firmware orchestration without compiling or contacting hardware."""

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
import tomlkit

from car.system.arduino.device.flash import FlashError
from car.system.arduino.management import menu as management
from car.system.arduino.management import workflow


@pytest.fixture
def car_root(car_tree):
    tmp_path = car_tree
    document = tomlkit.parse(
        (Path(__file__).resolve().parents[3] / "car/config.toml").read_text()
    )
    entry = {
        "version": "1.0.0",
        "protocol_version": 1,
        "fqbn": "arduino:avr:nano:cpu=atmega328",
    }
    document["firmware"] = {"first": {}, "second": {}}
    (tmp_path / "config.toml").write_text(tomlkit.dumps(document))
    for name, version in (("first", "1.0.0"), ("second", "2.0.0")):
        sketch = tmp_path / "system/arduino/sketches" / name
        sketch.mkdir(parents=True)
        (sketch / "firmware.toml").write_text(
            tomlkit.dumps({"firmware": {**entry, "version": version}, "parameters": {}})
        )
    return tmp_path


def test_selected_firmware_compiles_then_flashes_exact_artifacts(car_root):
    artifact = car_root / "build/artifacts"
    log = car_root / "flash/log.toml"
    calls = []
    pages = []

    def select(title, labels):
        assert "first — 1.0.0" in labels[0]
        assert "second — 2.0.0" in labels[1]
        return 1

    with (
        patch.object(
            workflow,
            "compile_firmware",
            side_effect=lambda *args, **kwargs: (
                calls.append(("compile", args)) or artifact
            ),
        ),
        patch.object(
            workflow,
            "flash_firmware",
            side_effect=lambda *args, **kwargs: calls.append(("flash", args)) or log,
        ),
    ):
        workflow.change_firmware(
            car_root, select=select, display=lambda *args: pages.append(args)
        )
    assert calls == [("compile", ("second", car_root)), ("flash", (artifact, car_root))]
    assert pages[0][0] == "Firmware changed"
    assert str(log) in pages[0][1]


@pytest.mark.parametrize("selection,compile_result", [(None, "unused"), (0, None)])
def test_back_or_compile_refusal_does_not_flash(car_root, selection, compile_result):
    with (
        patch.object(
            workflow, "compile_firmware", return_value=compile_result
        ) as compile_action,
        patch.object(workflow, "flash_firmware") as flash,
    ):
        workflow.change_firmware(car_root, select=lambda *args: selection)
    assert compile_action.call_count == (selection is not None)
    flash.assert_not_called()


@pytest.mark.parametrize(
    "error",
    [
        ValueError("Missing sketch"),
        subprocess.CalledProcessError(
            1, "compile", output="compiler details", stderr="compiler failed"
        ),
    ],
)
def test_compile_failure_reports_and_never_flashes(car_root, error):
    pages = []
    with (
        patch.object(workflow, "compile_firmware", side_effect=error),
        patch.object(workflow, "flash_firmware") as flash,
    ):
        workflow.change_firmware(
            car_root, select=lambda *args: 0, display=lambda *args: pages.append(args)
        )
    flash.assert_not_called()
    assert pages[0][0] == "Firmware change failed"
    assert str(error) in pages[0][1]
    if isinstance(error, subprocess.CalledProcessError):
        assert "compiler details" in pages[0][1]
        assert "compiler failed" in pages[0][1]


def test_flash_refusal_does_not_report_success(car_root):
    with (
        patch.object(workflow, "compile_firmware", return_value=car_root / "artifacts"),
        patch.object(workflow, "flash_firmware", return_value=None),
        patch.object(workflow, "show_page") as display,
    ):
        workflow.change_firmware(car_root, select=lambda *args: 0, display=display)
    display.assert_not_called()


def test_flash_failure_retains_log_in_error(car_root):
    pages = []
    with (
        patch.object(workflow, "compile_firmware", return_value=car_root / "artifacts"),
        patch.object(
            workflow,
            "flash_firmware",
            side_effect=FlashError("Identity mismatch", car_root / "log.toml"),
        ),
    ):
        workflow.change_firmware(
            car_root, select=lambda *args: 0, display=lambda *args: pages.append(args)
        )
    assert "Identity mismatch" in pages[0][1]
    assert str(car_root / "log.toml") in pages[0][1]


def test_no_registered_firmware_does_not_open_selection(car_root):
    path = car_root / "config.toml"
    config = tomlkit.parse(path.read_text())
    config["firmware"] = {}
    path.write_text(tomlkit.dumps(config))
    pages = []
    with patch.object(workflow, "compile_firmware") as compile_action:
        workflow.change_firmware(
            car_root,
            select=lambda *args: pytest.fail("Unexpected selection"),
            display=lambda *args: pages.append(args),
        )
    compile_action.assert_not_called()
    assert "No firmwares" in pages[0][1]


def test_interrupt_does_not_flash(car_root):
    with (
        patch.object(workflow, "compile_firmware", side_effect=KeyboardInterrupt),
        patch.object(workflow, "flash_firmware") as flash,
        pytest.raises(KeyboardInterrupt),
    ):
        workflow.change_firmware(car_root, select=lambda *args: 0)
    flash.assert_not_called()


def test_broken_entry_does_not_block_healthy_firmware(car_root):
    (car_root / "system/arduino/sketches/second/firmware.toml").unlink()
    pages = []

    def select(title, labels):
        assert len(labels) == 1 and labels[0].startswith("first —")
        return 0

    with (
        patch.object(workflow, "compile_firmware", return_value=None) as compile_action,
        patch.object(workflow, "flash_firmware") as flash,
    ):
        workflow.change_firmware(
            car_root, select=select, display=lambda *args: pages.append(args)
        )
    assert compile_action.call_args.args == ("first", car_root)
    assert pages[0][0] == "Unavailable firmware"
    assert "second" in pages[0][1]
    flash.assert_not_called()


def test_submenu_dispatches_change_firmware_second(car_root):
    choices = iter([1, None])

    def select(title, labels):
        assert labels == [
            "Identify and select device",
            "Change firmware",
            "Check firmware",
        ]
        return next(choices)

    with patch.object(management, "change_firmware") as action:
        management.arduino_menu(car_root, select=select)
    action.assert_called_once_with(car_root)
