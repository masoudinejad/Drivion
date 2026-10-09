"""Activate the configured hotspot when Wi-Fi has no active connection."""

import argparse
import subprocess
import sys
from pathlib import Path

from ..configuration import network_settings


def active_connection(interface):
    result = subprocess.run(
        ["nmcli", "--get-values", "GENERAL.CONNECTION", "device", "show", interface],
        capture_output=True,
        text=True,
        check=True,
    )
    connection = result.stdout.strip()
    return None if connection in ("", "--") else connection


def activate_fallback(settings):
    if active_connection(settings.wifi_interface) is not None:
        return False
    subprocess.run(
        [
            "nmcli",
            "connection",
            "up",
            settings.fallback_profile,
            "ifname",
            settings.wifi_interface,
        ],
        check=True,
    )
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--car-root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        activate_fallback(network_settings(args.car_root))
        return 0
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"Wi-Fi fallback error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
