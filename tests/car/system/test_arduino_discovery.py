"""Verify Arduino discovery preserves evidence and handles unavailable tools."""

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import tomllib

from car.system.arduino.discover import compact_report, discover, retain_firmware_info
from car.system.information.update import render_info

ROOT = Path(__file__).resolve().parents[3] / "car"


def test_refresh_retains_timestamped_identity_only_on_same_device():
    identity = {
        "address": "/dev/ttyUSB0",
        "serialNumber": "usb-id",
        "vid": "v",
        "pid": "p",
    }
    previous = {
        **identity,
        "firmware_name": "motor",
        "firmware_status": "verified",
        "firmware_checked_at": "then",
    }
    current = retain_firmware_info(dict(identity), previous)
    assert current["firmware_name"] == "motor"
    assert current["firmware_status"] == "last_verified"
    assert current["firmware_checked_at"] == "then"
    replacement = retain_firmware_info(
        {**identity, "serialNumber": "new-device"}, previous
    )
    assert "firmware_name" not in replacement
    assert "firmware_name" not in retain_firmware_info({"ports": []}, previous)


def test_refresh_preserves_identity_when_port_count_changes():
    previous = {"address": "/dev/ttyUSB0", "firmware_version": "1.0"}
    current = retain_firmware_info(
        {"ports": [{"address": "/dev/ttyUSB0"}, {"address": "/dev/ttyUSB1"}]}, previous
    )
    assert current["ports"][0]["firmware_version"] == "1.0"
    assert "firmware_version" not in current["ports"][1]
    flattened = retain_firmware_info({"address": "/dev/ttyUSB0"}, current)
    assert flattened["firmware_version"] == "1.0"


def response(value):
    return subprocess.CompletedProcess([], 0, json.dumps(value), "")


def test_candidates_unknown_ports_and_nested_metadata():
    listing = {
        "detected_ports": [
            {
                "port": {
                    "address": "/dev/ttyACM0",
                    "properties": {"vid": "0x2341", "serialNumber": "abc"},
                },
                "matching_boards": [{"name": "Uno", "fqbn": "arduino:avr:uno"}],
            },
            {"port": {"address": "/dev/ttyUSB0"}, "matching_boards": []},
        ]
    }
    details = {
        "config_options": [
            {"option": "cpu", "values": [{"value": "atmega328", "selected": True}]}
        ],
        "optional": None,
    }
    with patch(
        "car.system.arduino.discover.subprocess.run",
        side_effect=[
            response(listing),
            response({"platforms": [{"id": "arduino:avr", "installed": "1.8.6"}]}),
            response(details),
        ],
    ) as execute:
        report = discover(ROOT)
    assert report["status"] == "partial"
    assert report["selection"]["status"] == "ambiguous"
    assert report["ports"][1]["identification"] == "unidentified"
    assert (
        report["ports"][0]["matching_boards"][0]["specifications"]["config_options"]
        == details["config_options"]
    )
    assert execute.call_args.kwargs["timeout"] > 0
    rendered = render_info({"arduino": report})
    assert "[[arduino.ports]]" in rendered
    assert "[arduino.ports.port.properties]" in rendered
    assert "[[arduino.ports.matching_boards]]" in rendered
    assert tomllib.loads(rendered)["arduino"] == report


def test_cli_unavailable_does_not_claim_no_boards():
    with patch(
        "car.system.arduino.discover.subprocess.run",
        side_effect=FileNotFoundError("missing CLI"),
    ):
        report = discover(ROOT)
    assert report["status"] == "error"
    assert "missing CLI" in report["error"]


def test_single_port_is_saved_as_flat_arduino_section():
    report = {
        "status": "ok",
        "ports": [
            {
                "identification": "unidentified",
                "matching_boards": [],
                "port": {
                    "address": "/dev/ttyUSB0",
                    "protocol": "serial",
                    "properties": {
                        "serialNumber": "",
                        "vid": "0x1A86",
                        "pid": "0x7523",
                    },
                },
            }
        ],
    }
    compact = compact_report(report)
    assert compact == {
        "status": "ok",
        "identification": "unidentified",
        "matching_boards": [],
        "address": "/dev/ttyUSB0",
        "protocol": "serial",
        "serialNumber": "",
        "vid": "0x1A86",
        "pid": "0x7523",
    }
    rendered = render_info({"arduino": compact})
    assert "[arduino]" in rendered
    assert "arduino." not in rendered
    assert tomllib.loads(rendered)["arduino"] == compact


def test_detail_failure_retains_port():
    listing = {
        "detected_ports": [
            {
                "port": {"address": "usb"},
                "matching_boards": [{"fqbn": "vendor:core:board"}],
            }
        ]
    }
    with patch(
        "car.system.arduino.discover.subprocess.run",
        side_effect=[
            response(listing),
            response({"platforms": []}),
            subprocess.TimeoutExpired("cli", 30),
        ],
    ):
        report = discover(ROOT)
    assert report["status"] == "partial"
    assert report["ports"][0]["port"]["address"] == "usb"


def test_single_port_is_selected_automatically():
    listing = {
        "detected_ports": [{"port": {"address": "/dev/ttyUSB0"}, "matching_boards": []}]
    }
    with patch(
        "car.system.arduino.discover.subprocess.run",
        side_effect=[response(listing), response({"platforms": []})],
    ):
        report = discover(ROOT)
    assert report["selection"] == {
        "status": "selected",
        "address": "/dev/ttyUSB0",
    }


def test_malformed_nested_cli_output_is_reported():
    listing = {
        "detected_ports": [
            {"port": {"address": "/dev/ttyUSB0"}, "matching_boards": "invalid"}
        ]
    }
    with patch(
        "car.system.arduino.discover.subprocess.run",
        return_value=response(listing),
    ):
        report = discover(ROOT)
    assert report["status"] == "error"
    assert "matching_boards" in report["error"]
