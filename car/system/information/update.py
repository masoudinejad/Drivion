"""Evaluate hardware and software together and publish one system snapshot."""

import argparse
import json
import logging
import os
import platform
import pwd
import signal
import socket
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import tomllib

from ..arduino.device.discovery import compact_report, discover, retain_firmware_info
from ..configuration import (
    execution_settings,
    network_settings,
    python_environment_settings,
)

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


def existing_info(info_file):
    """Read usable generated tables, recovering from corrupt or malformed caches."""
    try:
        sections = tomllib.loads(Path(info_file).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (ValueError, UnicodeError) as error:
        logging.getLogger(__name__).warning(
            "Ignoring invalid system information: %s", error
        )
        return {}
    return {
        name: values for name, values in sections.items() if isinstance(values, dict)
    }


def existing_software(info_file):
    """Return usable historical deployment metadata, if any."""
    software = existing_info(info_file).get("software", {})
    return software if isinstance(software, dict) else {}


def runtime_info(car_root, config_root):
    """Run user-managed Python only as the car directory's unprivileged owner."""
    try:
        settings = python_environment_settings(config_root)
        with (Path(config_root) / "system/pyproject.toml").open("rb") as source:
            timeout = tomllib.load(source)["tool"]["drivion"]["verification"][
                "evaluation_timeout_seconds"
            ]
        if type(timeout) is not int or not 1 <= timeout <= 3600:
            raise ValueError(
                "Configure verification.evaluation_timeout_seconds between 1 and 3600"
            )
        python = Path(car_root) / settings.path / "bin/python"
        if not python.is_file():
            raise RuntimeError(
                "Configured Python environment is missing; run provisioning"
            )
        thread_limit = str(execution_settings(config_root).numerical_thread_limit)
        environment = {
            key: value
            for key, value in os.environ.items()
            if key not in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV")
        }
        environment["PYTHONPATH"] = str(Path(car_root).resolve())
        for name in (
            "OMP_NUM_THREADS",
            "OPENBLAS_NUM_THREADS",
            "TF_NUM_INTEROP_THREADS",
            "TF_NUM_INTRAOP_THREADS",
        ):
            environment[name] = thread_limit
        privileges = {}
        if os.geteuid() == 0:
            owner = pwd.getpwuid(Path(car_root).stat().st_uid)
            if owner.pw_uid == 0:
                raise RuntimeError("Runtime evaluation requires a non-root car owner")
            privileges = {
                "user": owner.pw_uid,
                "group": owner.pw_gid,
                "extra_groups": os.getgrouplist(owner.pw_name, owner.pw_gid),
            }
            environment.update(
                HOME=owner.pw_dir, USER=owner.pw_name, LOGNAME=owner.pw_name
            )
        with subprocess.Popen(
            [
                str(python),
                "-m",
                "system.information.runtime",
                str(Path(car_root).resolve()),
            ],
            cwd=car_root,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
            **privileges,
        ) as process:
            try:
                output, errors = process.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.communicate()
                raise RuntimeError(
                    f"Runtime evaluation exceeded {timeout} seconds"
                ) from None
            if process.returncode:
                raise RuntimeError(errors.strip() or "Runtime evaluation failed")
        report = json.loads(output)
        if not isinstance(report, dict):
            raise ValueError("Invalid runtime evaluation report")
        for name in ("configuration", "environment", "camera", "joystick"):
            if not isinstance(report.get(name), dict) or "status" not in report[name]:
                raise ValueError(f"Invalid runtime evaluation section: {name}")
        return {
            name: report[name]
            for name in ("configuration", "environment", "camera", "joystick")
        }
    except (
        ImportError,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
        KeyError,
    ) as error:
        return {
            name: {"status": "error", "error": str(error)}
            for name in ("configuration", "environment", "camera", "joystick")
        }


def collect_info(
    car_root,
    software=None,
    device_tree=Path("/proc/device-tree"),
    config_root=None,
):
    """Evaluate hardware and software once, preserving deployment metadata only.

    Device discovery never opens serial communication or starts camera capture.
    Independent failures are recorded so a partial report is still publishable.
    """
    car_root = Path(car_root)
    config_root = Path(config_root) if config_root is not None else car_root
    previous = existing_info(car_root / INFO_PATH)
    sections = {
        "software": previous.get("software", {}) if software is None else software,
        "system": {
            "hostname": socket.gethostname(),
            "operating_system": _os_name(),
            "kernel": platform.release(),
            "architecture": platform.machine(),
        },
    }
    try:
        sections["hardware"] = {"status": "ok", **hardware_info(device_tree)}
    except (OSError, RuntimeError, ValueError) as error:
        sections["hardware"] = {"status": "error", "error": str(error)}
    try:
        sections["arduino"] = retain_firmware_info(
            compact_report(discover(car_root, config_root)), previous.get("arduino", {})
        )
        if sections["arduino"]["status"] == "ok" and not (
            sections["arduino"].get("address") or sections["arduino"].get("ports")
        ):
            sections["arduino"]["status"] = "missing"
    except (OSError, RuntimeError, TypeError, ValueError) as error:
        sections["arduino"] = {"status": "error", "error": str(error)}
    try:
        settings = network_settings(config_root)
        sections["network"] = {
            "status": "ok",
            "wifi_interface": settings.wifi_interface,
            "fallback_ssid": settings.fallback_ssid(
                sections["hardware"]["serial_number"]
            ),
            "fallback_address": settings.fallback_ipv4_address,
        }
    except (OSError, RuntimeError, TypeError, ValueError, KeyError) as error:
        sections["network"] = {"status": "error", "error": str(error)}
    sections.update(runtime_info(car_root, config_root))
    failed = [
        name
        for name in (
            "hardware",
            "arduino",
            "network",
            "configuration",
            "environment",
            "camera",
            "joystick",
        )
        if sections[name].get("status") != "ok"
    ]
    sections["checks"] = {
        "status": (
            "error"
            if any(sections[name].get("status") == "error" for name in failed)
            else "warning"
            if failed
            else "ok"
        ),
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "failed": failed,
    }
    return sections


def refresh_info(car_root, **kwargs):
    """Collect once and atomically publish the complete central snapshot."""
    sections = collect_info(car_root, **kwargs)
    publish(Path(car_root) / INFO_PATH, sections)
    return sections


def publish(info_file, sections):
    """Atomically replace the record only when collected information changed."""
    info_file = Path(info_file)
    if info_file.is_symlink() or info_file.parent.is_symlink():
        raise ValueError("System information destination must not be a symlink")
    content = render_info(sections)
    try:
        if info_file.read_text() == content:
            return content
    except (FileNotFoundError, UnicodeError):
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
            settings.command_path,
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
        timeout=settings.command_timeout_seconds,
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--car-root", type=Path, required=True)
    parser.add_argument(
        "--config-root",
        type=Path,
        help="Root containing protected config.toml and system/pyproject.toml",
    )
    parser.add_argument("--software-stdin", action="store_true")
    parser.add_argument("--device-tree", type=Path, default=Path("/proc/device-tree"))
    parser.add_argument("--update-hotspot", action="store_true")
    parser.add_argument("--print", action="store_true", dest="print_info")
    args = parser.parse_args(argv)
    try:
        software = software_from_text(sys.stdin.read()) if args.software_stdin else None
        config_root = args.config_root or args.car_root
        sections = refresh_info(
            args.car_root,
            software=software,
            device_tree=args.device_tree,
            config_root=config_root,
        )
        content = render_info(sections)
        if args.update_hotspot:
            if sections["network"]["status"] != "ok":
                raise RuntimeError(sections["network"]["error"])
            update_hotspot(
                network_settings(config_root), sections["network"]["fallback_ssid"]
            )
        if args.print_info:
            print(content, end="")
        return 0
    except (
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
        subprocess.SubprocessError,
    ) as error:
        print(f"System information error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
