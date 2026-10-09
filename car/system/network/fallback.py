"""Activate the configured hotspot when Wi-Fi has no active connection."""

import argparse
import subprocess
import sys
from pathlib import Path

from ..configuration import network_settings


def active_connection(command, interface, timeout):
    result = subprocess.run(
        [command, "--get-values", "GENERAL.CONNECTION", "device", "show", interface],
        capture_output=True,
        text=True,
        check=True,
        timeout=timeout,
    )
    connection = result.stdout.strip()
    return None if connection in ("", "--") else connection


def activate_fallback(settings):
    if (
        active_connection(
            settings.command_path,
            settings.wifi_interface,
            settings.command_timeout_seconds,
        )
        is not None
    ):
        return False
    subprocess.run(
        [
            settings.command_path,
            "connection",
            "up",
            settings.fallback_profile,
            "ifname",
            settings.wifi_interface,
        ],
        check=True,
        timeout=settings.command_timeout_seconds,
    )
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--car-root", type=Path, required=True)
    parser.add_argument(
        "--config-root",
        type=Path,
        help="Root containing the protected config.toml",
    )
    args = parser.parse_args(argv)
    try:
        activate_fallback(network_settings(args.config_root or args.car_root))
        return 0
    except (OSError, TypeError, ValueError, subprocess.SubprocessError) as error:
        print(f"Wi-Fi fallback error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
