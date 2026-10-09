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
from pathlib import Path, PurePosixPath

# Allow direct invocation as well as python -m dev.ansible.run.
ROOT = Path(__file__).resolve().parents[2]
if not __package__:
    sys.path.insert(0, str(ROOT))

from car.system.configuration import arduino_settings, network_settings, uv_settings
from car.system.environment import environment_path
from car.system.provisioning import system_settings
from dev.sync import sync_car


def hotspot_password(settings):
    password = settings.get("PI_HOTSPOT_PASSWORD") or settings.get("PI_PASSWORD", "")
    try:
        password.encode("ascii")
    except UnicodeEncodeError as error:
        raise ValueError("PI_HOTSPOT_PASSWORD must contain printable ASCII") from error
    if not 8 <= len(password) <= 63 or not password.isprintable():
        raise ValueError(
            "PI_HOTSPOT_PASSWORD (or PI_PASSWORD fallback) must be 8-63 printable ASCII characters"
        )
    return password


def build_inventory(settings):
    # Reuse sync's validation and SSH options, including the selected agent key.
    command = sync_car.build_command(settings)
    ssh = shlex.split(command[command.index("--rsync-path") - 1])
    relative_environment = environment_path(ROOT / "car").relative_to(ROOT / "car")
    network = network_settings(ROOT / "car")
    uv = uv_settings(ROOT / "car")
    arduino = arduino_settings(ROOT / "car")
    packages, _ = system_settings(ROOT / "car")
    car_root = settings.get("PI_CAR_PATH") or f"/home/{settings['PI_USER']}/car"
    car_home = f"/home/{settings['PI_USER']}"
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
                            "arduino_cli_version": arduino.cli_version,
                            "arduino_cli_archive_name": arduino.cli_archive_name,
                            "arduino_cli_archive_sha256": arduino.cli_archive_sha256,
                            "arduino_cli_release_url": arduino.cli_release_url,
                            "arduino_cli_install_directory": arduino.cli_install_directory,
                            "arduino_cli_archive_executable": arduino.cli_archive_executable,
                            "arduino_cli_executable_path": arduino.cli_executable_path,
                            "arduino_data_directory": str(
                                PurePosixPath(car_home) / arduino.data_directory
                            ),
                            "arduino_download_directory": str(
                                PurePosixPath(car_home) / arduino.download_directory
                            ),
                            "arduino_config_path": str(
                                PurePosixPath(car_home) / arduino.config_path
                            ),
                            "arduino_sketchbook_directory": str(
                                PurePosixPath(car_root) / arduino.sketchbook_directory
                            ),
                            "arduino_serial_group": arduino.serial_group,
                            "arduino_avr_core": arduino.avr_core,
                            "arduino_avr_core_version": arduino.avr_core_version,
                            "controller_root": str(ROOT),
                            "controller_python": sys.executable,
                            "wifi_interface": network.wifi_interface,
                            "wifi_fallback_profile": network.fallback_profile,
                            "wifi_fallback_ssid_prefix": network.fallback_ssid_prefix,
                            "wifi_fallback_ipv4_cidr": network.fallback_ipv4_cidr,
                            "wifi_fallback_delay_seconds": network.fallback_delay_seconds,
                            "wifi_fallback_timer_accuracy_seconds": (
                                network.fallback_timer_accuracy_seconds
                            ),
                            "uv_version": uv.version,
                            "uv_archive_name": uv.archive_name,
                            "uv_archive_sha256": uv.archive_sha256,
                            "uv_release_url": uv.release_url,
                            "uv_install_directory": uv.install_directory,
                            "uv_executable_directory": uv.executable_directory,
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
    parser.add_argument(
        "--arduino-only",
        action="store_true",
        help="Install and verify Arduino CLI, serial access, and the AVR core only",
    )
    args = parser.parse_args(argv)
    try:
        settings = sync_car.read_settings(ROOT / "dev/sync/.env")
        inventory = build_inventory(settings)
        if not args.syntax_check and not settings.get("PI_PASSWORD"):
            raise ValueError("Set PI_PASSWORD in dev/sync/.env for sudo")
        configured_hotspot_password = (
            "" if args.syntax_check or args.arduino_only else hotspot_password(settings)
        )
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
        environment["DRIVION_HOTSPOT_PASSWORD"] = configured_hotspot_password
        with tempfile.TemporaryDirectory(prefix="drivion-ansible-") as directory:
            path = Path(directory) / "inventory.json"
            path.write_text(json.dumps(inventory))
            command = [
                "ansible-playbook",
                "-i",
                str(path),
                str(Path(__file__).with_name("update.yml")),
            ]
            if args.arduino_only:
                command.extend(["--tags", "arduino"])
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
