"""Verify stable hotspot identity and boot-time hardware refreshes."""

import subprocess
from unittest.mock import patch

import pytest
import tomllib

from car.system import configuration
from car.system.information import update as system_info
from car.system.network import fallback as wifi_fallback


@pytest.fixture(autouse=True)
def mock_discovery():
    with patch.object(
        system_info, "discover", return_value={"status": "ok", "ports": []}
    ):
        yield


def config(root):
    (root / "config.toml").write_text(
        """[system.network]
wifi_interface = "wlan0"
fallback_profile = "drivion-hotspot"
fallback_ssid_prefix = "Drivion"
fallback_ssid_serial_characters = 6
fallback_ipv4_address = "10.42.0.1"
fallback_ipv4_prefix_length = 24
fallback_delay_seconds = 60
fallback_timer_accuracy_seconds = 1
"""
    )


def device_tree(root, model="Raspberry Pi 5", serial="00000000a4f29c"):
    root.mkdir(exist_ok=True)
    (root / "model").write_bytes(model.encode() + b"\0")
    (root / "serial-number").write_bytes(serial.encode() + b"\0")


def test_publish_preserves_software_and_refreshes_changed_hardware(tmp_path):
    config(tmp_path)
    info_file = tmp_path / "system/info.toml"
    info_file.parent.mkdir()
    info_file.write_text('[software]\nversion = "v1.0.0"\n')
    tree = tmp_path / "device-tree"
    device_tree(tree)
    sections = system_info.collect_info(tmp_path, device_tree=tree)
    system_info.publish(info_file, sections)
    first = tomllib.loads(info_file.read_text())
    assert first["software"]["version"] == "v1.0.0"
    assert first["hardware"]["serial_number"] == "00000000a4f29c"
    assert first["network"]["fallback_ssid"] == "Drivion-A4F29C"
    assert first["network"]["fallback_address"] == "10.42.0.1"

    device_tree(tree, model="Raspberry Pi 4", serial="00000000123456")
    system_info.publish(info_file, system_info.collect_info(tmp_path, device_tree=tree))
    refreshed = tomllib.loads(info_file.read_text())
    assert refreshed["software"] == first["software"]
    assert refreshed["hardware"]["model"] == "Raspberry Pi 4"
    assert refreshed["network"]["fallback_ssid"] == "Drivion-123456"


def test_hotspot_profile_receives_current_ssid():
    settings = configuration.NetworkSettings(
        "wlan0", "drivion-hotspot", "Drivion", 6, "10.42.0.1", 24, 60, 1
    )
    with patch.object(system_info.subprocess, "run") as execute:
        system_info.update_hotspot(settings, "Drivion-A4F29C")
    assert execute.call_args.args[0][-1] == "Drivion-A4F29C"
    assert execute.call_args.kwargs["check"] is True


def test_fallback_only_activates_without_an_active_wifi_connection():
    settings = configuration.NetworkSettings(
        "wlan0", "drivion-hotspot", "Drivion", 6, "10.42.0.1", 24, 60, 1
    )
    connected = subprocess.CompletedProcess([], 0, stdout="home-wifi\n")
    disconnected = subprocess.CompletedProcess([], 0, stdout="--\n")
    with patch.object(wifi_fallback.subprocess, "run", return_value=connected) as run:
        assert not wifi_fallback.activate_fallback(settings)
        assert run.call_count == 1
    with patch.object(
        wifi_fallback.subprocess,
        "run",
        side_effect=[disconnected, subprocess.CompletedProcess([], 0)],
    ) as run:
        assert wifi_fallback.activate_fallback(settings)
        assert run.call_args.args[0] == [
            "nmcli",
            "connection",
            "up",
            "drivion-hotspot",
            "ifname",
            "wlan0",
        ]
