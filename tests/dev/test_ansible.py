"""Validate Ansible target selection and password handling without a live Pi."""

import json
import subprocess
from pathlib import Path, PurePosixPath
from unittest.mock import patch

import pytest
import tomllib

from dev.ansible import run


def test_inventory_reuses_ssh_settings_without_password(tmp_path):
    key = tmp_path / "personal.pub"
    key.write_text("ssh-ed25519 example")
    settings = {
        "PI_HOST": "pi.local",
        "PI_USER": "driver",
        "PI_PASSWORD": "private-value",
        "SSH_AUTH_SOCK": "/tmp/example-agent.sock",
        "PI_SSH_PUBLIC_KEY": str(key),
    }
    inventory = run.build_inventory(settings)
    host = inventory["all"]["children"]["raspberry_pi"]["hosts"]["car"]
    assert host["ansible_host"] == "pi.local"
    assert host["ansible_user"] == "driver"
    assert "IdentityAgent=SSH_AUTH_SOCK" in host["ansible_ssh_common_args"]
    assert str(key) in host["ansible_ssh_common_args"]
    assert settings["PI_PASSWORD"] not in json.dumps(inventory)
    assert host["wifi_interface"] == "wlan0"
    assert host["wifi_fallback_ipv4_cidr"] == "10.42.0.1/24"
    assert host["wifi_fallback_delay_seconds"] == 60
    assert host["wifi_fallback_timer_accuracy_seconds"] == 1


def test_runner_uses_sudo_password_only_in_environment():
    settings = {
        "PI_HOST": "pi.local",
        "PI_USER": "driver",
        "PI_PASSWORD": "private-value",
    }
    captured = {}

    def execute(command, **kwargs):
        captured["inventory"] = Path(command[command.index("-i") + 1])
        assert settings["PI_PASSWORD"] not in captured["inventory"].read_text()
        assert settings["PI_PASSWORD"] not in " ".join(command)
        assert kwargs["env"]["ANSIBLE_BECOME_PASS"] == settings["PI_PASSWORD"]
        assert kwargs["env"]["DRIVION_HOTSPOT_PASSWORD"] == settings["PI_PASSWORD"]
        assert "--check" in command
        return subprocess.CompletedProcess(command, 2)

    with (
        patch.object(run.sync_car, "read_settings", return_value=settings),
        patch.object(run.shutil, "which", return_value="/bin/ansible-playbook"),
        patch.object(run.subprocess, "run", side_effect=execute),
    ):
        assert run.main(["--check"]) == 2
    assert not captured["inventory"].exists()


def test_missing_sudo_password_prevents_execution():
    with (
        patch.object(
            run.sync_car,
            "read_settings",
            return_value={"PI_HOST": "pi.local", "PI_USER": "driver"},
        ),
        patch.object(run.subprocess, "run") as execute,
    ):
        assert run.main([]) == 1
        execute.assert_not_called()


def test_hotspot_password_defaults_to_sudo_password():
    assert run.hotspot_password({"PI_PASSWORD": "general-password"}) == (
        "general-password"
    )
    assert (
        run.hotspot_password(
            {"PI_PASSWORD": "general-password", "PI_HOTSPOT_PASSWORD": "wifi-password"}
        )
        == "wifi-password"
    )


def test_hotspot_password_must_be_a_valid_wpa_passphrase():
    for password in ("short", "contains\nnewline", "x" * 64, "pässword1"):
        with pytest.raises(ValueError):
            run.hotspot_password(
                {"PI_PASSWORD": "general-password", "PI_HOTSPOT_PASSWORD": password}
            )


def test_inventory_reads_system_packages_from_pyproject():
    configured = tomllib.loads((run.ROOT / "car/system/pyproject.toml").read_text())[
        "tool"
    ]["drivion"]["provisioning"]["packages"]
    inventory = run.build_inventory({"PI_HOST": "pi.local", "PI_USER": "driver"})
    host = inventory["all"]["children"]["raspberry_pi"]["hosts"]["car"]
    assert host["system_packages"] == configured
    with patch.object(run, "system_settings", return_value=(["custom-package"], [])):
        inventory = run.build_inventory({"PI_HOST": "pi.local", "PI_USER": "driver"})
    assert inventory["all"]["children"]["raspberry_pi"]["hosts"]["car"][
        "system_packages"
    ] == ["custom-package"]


def test_inventory_reads_arduino_settings_from_central_config():
    config = run.arduino_settings(run.ROOT / "car")
    inventory = run.build_inventory({"PI_HOST": "pi.local", "PI_USER": "driver"})
    host = inventory["all"]["children"]["raspberry_pi"]["hosts"]["car"]
    assert host["arduino_cli_version"] == config.cli_version
    assert host["arduino_cli_archive_name"] == config.cli_archive_name
    assert host["arduino_cli_archive_sha256"] == config.cli_archive_sha256
    assert host["arduino_avr_core_version"] == config.avr_core_version
    assert host["arduino_data_directory"] == str(
        PurePosixPath("/home/driver") / config.data_directory
    )
    assert host["arduino_sketchbook_directory"] == str(
        PurePosixPath("/home/driver/car") / config.sketchbook_directory
    )


def test_inventory_reads_uv_settings_from_central_config():
    config = run.uv_settings(run.ROOT / "car")
    inventory = run.build_inventory({"PI_HOST": "pi.local", "PI_USER": "driver"})
    host = inventory["all"]["children"]["raspberry_pi"]["hosts"]["car"]
    assert host["uv_version"] == config.version
    assert host["uv_archive_sha256"] == config.archive_sha256
    assert host["uv_install_directory"] == config.install_directory
    assert host["uv_executable_directory"] == config.executable_directory
