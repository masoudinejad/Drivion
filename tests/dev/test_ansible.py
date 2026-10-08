"""Validate Ansible target selection and password handling without a live Pi."""

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

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
