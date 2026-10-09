"""Validate Ansible target selection and password handling without a live Pi."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path, PurePosixPath
from unittest.mock import patch

import pytest
import tomllib

from dev.ansible import run


def test_protected_service_module_set_imports_without_car_dependencies(tmp_path):
    """Validate that Ansible deploys every dependency needed by root boot services."""
    import yaml

    tasks = yaml.safe_load((run.ROOT / "dev/ansible/tasks/network.yml").read_text())
    modules = next(
        task["loop"]
        for task in tasks
        if task["name"] == "Install the protected Drivion service modules"
    )
    for module in modules:
        destination = tmp_path / "system" / module["destination"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(run.ROOT / "car/system" / module["source"], destination)
    subprocess.run(
        [
            sys.executable,
            "-S",
            "-c",
            (
                "from system.information.update import collect_info; "
                "from system.arduino.device.discovery import discover; "
                "from system.network.fallback import activate_fallback"
            ),
        ],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(tmp_path)},
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )


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
    toolchain = run.arduino_toolchain_settings(run.ROOT / "car")
    inventory = run.build_inventory({"PI_HOST": "pi.local", "PI_USER": "driver"})
    host = inventory["all"]["children"]["raspberry_pi"]["hosts"]["car"]
    assert host["arduino_address"] == config.address
    assert host["arduino_cli_version"] == toolchain.cli_version
    assert host["arduino_cli_archive_name"] == toolchain.cli_archive_name
    assert host["arduino_cli_archive_sha256"] == toolchain.cli_archive_sha256
    assert host["arduino_avr_core_version"] == toolchain.avr_core_version
    assert host["arduino_data_directory"] == str(
        PurePosixPath("/home/driver") / toolchain.data_directory
    )
    assert host["arduino_sketchbook_directory"] == str(
        PurePosixPath("/home/driver/car") / config.sketchbook_directory
    )


def test_inventory_reads_uv_settings_from_central_config():
    config = run.uv_settings(run.ROOT / "car")
    inventory = run.build_inventory({"PI_HOST": "pi.local", "PI_USER": "driver"})
    host = inventory["all"]["children"]["raspberry_pi"]["hosts"]["car"]
    assert host["uv_installer_url"] == config.installer_url
    assert host["uv_executable_directory"] == config.executable_directory


def test_arduino_only_selects_tasks_without_hotspot_requirement():
    settings = {"PI_HOST": "pi.local", "PI_USER": "driver", "PI_PASSWORD": "short"}

    def execute(command, **kwargs):
        assert command[command.index("--tags") + 1] == "arduino"
        assert kwargs["env"]["DRIVION_HOTSPOT_PASSWORD"] == ""
        assert kwargs["env"]["ANSIBLE_BECOME_PASS"] == "short"
        return subprocess.CompletedProcess(command, 0)

    with (
        patch.object(run.sync_car, "read_settings", return_value=settings),
        patch.object(run.shutil, "which", return_value="/bin/ansible-playbook"),
        patch.object(run.subprocess, "run", side_effect=execute),
    ):
        assert run.main(["--arduino-only"]) == 0


def test_arduino_core_conditions_with_cli_1_5_json(tmp_path):
    """Evaluate the real Ansible expressions against installed and absent cores."""
    import os

    import yaml

    tasks = yaml.safe_load((run.ROOT / "dev/ansible/tasks/arduino.yml").read_text())
    record = next(task for task in tasks if "ansible.builtin.set_fact" in task)
    condition = record["ansible.builtin.set_fact"]["arduino_avr_core_is_installed"]
    verify = next(task for task in tasks if "ansible.builtin.assert" in task)
    assertion = verify["ansible.builtin.assert"]["that"][0]
    checks = []
    for platforms, expected in (
        ([], False),
        ([{"id": "arduino:avr", "installed_version": "1.8.6"}], True),
        ([{"id": "arduino:avr", "installed_version": "1.8.5"}], False),
        ([{"id": "arduino:avr"}], False),
        ([{"id": "other:avr", "installed_version": "1.8.6"}], False),
    ):
        result = {"rc": 0, "stdout": json.dumps({"platforms": platforms})}
        checks.append(
            {
                "ansible.builtin.assert": {
                    "that": [
                        f"({condition.removeprefix('{{').removesuffix('}}').strip()}) == expected",
                        f"({assertion}) == expected",
                    ]
                },
                "vars": {
                    "installed_arduino_cores": result,
                    "verified_arduino_cores": result,
                    "arduino_avr_core": "arduino:avr",
                    "arduino_avr_core_version": "1.8.6",
                    "expected": expected,
                },
            }
        )
    play = tmp_path / "verify.json"
    play.write_text(
        json.dumps([{"hosts": "localhost", "gather_facts": False, "tasks": checks}])
    )
    environment = os.environ.copy()
    environment["ANSIBLE_LOCAL_TEMP"] = str(tmp_path / "ansible")
    result = subprocess.run(
        ["ansible-playbook", "-i", "localhost,", "-c", "local", str(play)],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_uv_updates_only_after_managed_dry_run_reports_newer_release():
    import yaml

    tasks = yaml.safe_load((run.ROOT / "dev/ansible/tasks/uv.yml").read_text())
    check = next(task for task in tasks if task["name"].startswith("Check whether"))
    assert "--dry-run" in check["ansible.builtin.command"]["argv"]
    update = next(task for task in tasks if task["name"].startswith("Update uv only"))
    assert any("Would update uv" in condition for condition in update["when"])
    assert update["changed_when"] is True


def test_wifi_profile_is_modified_only_when_properties_differ():
    import yaml

    tasks = yaml.safe_load((run.ROOT / "dev/ansible/tasks/network.yml").read_text())
    inspect = next(
        task
        for task in tasks
        if task["name"] == "Inspect the fallback hotspot settings"
    )
    assert inspect["no_log"] is True
    configure = next(
        task
        for task in tasks
        if task["name"] == "Configure the fallback hotspot profile"
    )
    assert any("stdout_lines" in condition for condition in configure["when"])
    assert configure["no_log"] is True


def test_root_services_use_protected_toml_snapshot():
    templates = run.ROOT / "dev/ansible/templates/network"
    for name in (
        "drivion-system-info.service.j2",
        "drivion-wifi-fallback.service.j2",
    ):
        content = (templates / name).read_text()
        assert "--config-root {{ service_configuration_directory }}" in content
