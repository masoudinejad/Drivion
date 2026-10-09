"""Publish stable software and current Raspberry Pi system information."""

import argparse
import json
import os
import platform
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

import tomllib

from ..arduino.discover import compact_report, discover
from ..configuration import network_settings

INFO_PATH = Path("system/info.toml")


def _read_text(path):
    return Path(path).read_bytes().rstrip(b"\0\n").decode()


def _os_name(path=Path("/etc/os-release")):
    try:
        for line in path.read_text().splitlines():
            key, separator, value = line.partition("=")
            if key == "PRETTY_NAME" and separator:
                return value.strip().strip('"')
    except OSError:
        pass
    return platform.system()


def hardware_info(device_tree=Path("/proc/device-tree")):
    """Read identifiers that change when an SD card moves to another Pi."""
    device_tree = Path(device_tree)
    try:
        model = _read_text(device_tree / "model")
        serial = _read_text(device_tree / "serial-number")
    except (OSError, UnicodeError) as error:
        raise RuntimeError(
            "Unable to read Raspberry Pi model and serial number"
        ) from error
    if not serial:
        raise RuntimeError("Raspberry Pi serial number is empty")
    return {"model": model, "serial_number": serial}


def _toml_value(value):
    if isinstance(value, dict):
        return (
            "{ "
            + ", ".join(
                f"{json.dumps(key)} = {_toml_value(item)}"
                for key, item in value.items()
            )
            + " }"
        )
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(item) for item in value) + "]"
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (str, int, float)):
        return json.dumps(value)
    raise TypeError(f"Unsupported system information value: {type(value).__name__}")


def render_info(sections):
    """Render nested records as tables and arrays of tables for readability."""
    lines = ["# Generated system information; do not edit."]

    def key_name(key):
        return (
            key
            if key.isascii() and key.replace("_", "").replace("-", "").isalnum()
            else json.dumps(key)
        )

    def table(path, values, array=False):
        name = ".".join(key_name(key) for key in path)
        lines.extend(("", f"[[{name}]]" if array else f"[{name}]"))
        children = []
        for key, value in values.items():
            if isinstance(value, dict):
                children.append((path + (key,), value, False))
            elif (
                isinstance(value, list)
                and value
                and all(isinstance(item, dict) for item in value)
            ):
                children.extend((path + (key,), item, True) for item in value)
            else:
                lines.append(f"{key_name(key)} = {_toml_value(value)}")
        for child_path, child_values, child_array in children:
            table(child_path, child_values, child_array)

    for section, values in sections.items():
        table((section,), values)
    return "\n".join(lines) + "\n"


def software_from_text(content):
    if not content:
        return {}
    parsed = tomllib.loads(content)
    software = parsed.get("software", {})
    if not isinstance(software, dict):
        raise TypeError("The software information must be a TOML table")
    return software


def existing_software(info_file):
    try:
        return software_from_text(Path(info_file).read_text())
    except FileNotFoundError:
        return {}


def collect_info(car_root, software=None, device_tree=Path("/proc/device-tree")):
    car_root = Path(car_root)
    settings = network_settings(car_root)
    hardware = hardware_info(device_tree)
    return {
        "software": (
            existing_software(car_root / INFO_PATH) if software is None else software
        ),
        "hardware": hardware,
        "arduino": compact_report(discover(car_root)),
        "system": {
            "hostname": socket.gethostname(),
            "operating_system": _os_name(),
            "kernel": platform.release(),
            "architecture": platform.machine(),
        },
        "network": {
            "wifi_interface": settings.wifi_interface,
            "fallback_ssid": settings.fallback_ssid(hardware["serial_number"]),
            "fallback_address": settings.fallback_ipv4_address,
        },
    }


def publish(info_file, sections):
    """Atomically replace the record only when collected information changed."""
    info_file = Path(info_file)
    if info_file.is_symlink() or info_file.parent.is_symlink():
        raise ValueError("System information destination must not be a symlink")
    content = render_info(sections)
    try:
        if info_file.read_text() == content:
            return content
    except FileNotFoundError:
        pass
    info_file.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", dir=info_file.parent, delete=False
    ) as stream:
        temporary = Path(stream.name)
        stream.write(content)
    try:
        temporary.chmod(0o644)
        os.replace(temporary, info_file)
    finally:
        temporary.unlink(missing_ok=True)
    return content


def update_hotspot(settings, ssid):
    subprocess.run(
        [
            "nmcli",
            "connection",
            "modify",
            settings.fallback_profile,
            "connection.autoconnect",
            "no",
            "connection.interface-name",
            settings.wifi_interface,
            "802-11-wireless.ssid",
            ssid,
        ],
        check=True,
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--car-root", type=Path, required=True)
    parser.add_argument("--software-stdin", action="store_true")
    parser.add_argument("--device-tree", type=Path, default=Path("/proc/device-tree"))
    parser.add_argument("--update-hotspot", action="store_true")
    parser.add_argument("--print", action="store_true", dest="print_info")
    args = parser.parse_args(argv)
    try:
        software = software_from_text(sys.stdin.read()) if args.software_stdin else None
        settings = network_settings(args.car_root)
        sections = collect_info(args.car_root, software, args.device_tree)
        content = publish(args.car_root / INFO_PATH, sections)
        if args.update_hotspot:
            update_hotspot(settings, sections["network"]["fallback_ssid"])
        if args.print_info:
            print(content, end="")
        return 0
    except (
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
        subprocess.CalledProcessError,
    ) as error:
        print(f"System information error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
