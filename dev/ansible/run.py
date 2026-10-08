#!/usr/bin/env python3
"""Run Raspberry Pi maintenance using the existing local sync configuration."""

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Allow direct invocation as well as python -m dev.ansible.run.
ROOT = Path(__file__).resolve().parents[2]
if not __package__:
    sys.path.insert(0, str(ROOT))

from car.system.environment import environment_path
from car.system.provisioning import system_settings
from dev.sync import sync_car


def build_inventory(settings):
    # Reuse sync's validation and SSH options, including the selected agent key.
    command = sync_car.build_command(settings)
    ssh = shlex.split(command[command.index("--rsync-path") - 1])
    relative_environment = environment_path(ROOT / "car").relative_to(ROOT / "car")
    packages, _ = system_settings(ROOT / "car")
    car_root = settings.get("PI_CAR_PATH") or f"/home/{settings['PI_USER']}/car"
    return {
        "all": {
            "children": {
                "raspberry_pi": {
                    "hosts": {
                        "car": {
                            "ansible_host": settings["PI_HOST"],
                            "ansible_user": settings["PI_USER"],
                            "ansible_connection": "ssh",
                            "ansible_python_interpreter": "/usr/bin/python3",
                            "ansible_ssh_common_args": shlex.join(ssh[1:]),
                            "car_root": car_root,
                            "system_packages": packages,
                            "car_environment_name": relative_environment.name,
                            "car_environment_path": f"{car_root}/{relative_environment}",
                            "controller_root": str(ROOT),
                            "controller_python": sys.executable,
                        }
                    }
                }
            }
        }
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="Preview changes with Ansible check mode"
    )
    parser.add_argument(
        "--syntax-check",
        action="store_true",
        help="Validate the playbook without connecting",
    )
    args = parser.parse_args(argv)
    try:
        settings = sync_car.read_settings(ROOT / "dev/sync/.env")
        inventory = build_inventory(settings)
        if not args.syntax_check and not settings.get("PI_PASSWORD"):
            raise ValueError("Set PI_PASSWORD in dev/sync/.env for sudo")
        if shutil.which("ansible-playbook") is None:
            raise ValueError(
                "Run through uv run --project dev to use the Ansible environment"
            )
        environment = os.environ.copy()
        if settings.get("SSH_AUTH_SOCK"):
            environment["SSH_AUTH_SOCK"] = str(
                Path(settings["SSH_AUTH_SOCK"]).expanduser()
            )
        # The sudo password never goes into inventory files or command arguments.
        environment["ANSIBLE_BECOME_PASS"] = settings.get("PI_PASSWORD", "")
        with tempfile.TemporaryDirectory(prefix="drivion-ansible-") as directory:
            path = Path(directory) / "inventory.json"
            path.write_text(json.dumps(inventory))
            command = [
                "ansible-playbook",
                "-i",
                str(path),
                str(Path(__file__).with_name("update.yml")),
            ]
            if args.check:
                command.append("--check")
            if args.syntax_check:
                command.append("--syntax-check")
            return subprocess.run(
                command, env=environment, cwd=ROOT, check=False
            ).returncode
    except (OSError, ValueError) as error:
        print(f"Ansible setup error: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
