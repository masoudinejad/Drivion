"""Shared firmware identity, artifact integrity and flashing settings contracts."""

import hashlib
import math
import re
from pathlib import Path


def validate_flash_configuration(settings):
    """Require all operation settings in TOML, with bounded serial waits."""
    fields = {
        "log_directory",
        "command_timeout_seconds",
        "baud_rate",
        "query_command",
        "boot_wait_seconds",
        "query_timeout_seconds",
        "read_timeout_seconds",
        "max_response_bytes",
    }
    if not isinstance(settings, dict) or set(settings) != fields:
        raise ValueError("Configure exactly the supported firmware_flash settings")
    value = settings["log_directory"]
    if not isinstance(value, str):
        raise TypeError("Flash log directory must be a path string")
    path = Path(value)
    if (
        path.is_absolute()
        or ".." in path.parts
        or not path.is_relative_to("system/arduino")
    ):
        raise ValueError("Flash logs must be inside system/arduino")
    for key, maximum in (
        ("command_timeout_seconds", 3600),
        ("baud_rate", 4000000),
        ("max_response_bytes", 65536),
    ):
        if type(settings[key]) is not int or not 1 <= settings[key] <= maximum:
            raise ValueError(f"Configure a valid firmware_flash.{key}")
    for key in ("boot_wait_seconds", "query_timeout_seconds", "read_timeout_seconds"):
        value = settings[key]
        minimum = 0 if key == "boot_wait_seconds" else 0.001
        if (
            type(value) not in (int, float)
            or not math.isfinite(value)
            or not minimum <= value <= 60
        ):
            raise ValueError(f"Configure a bounded firmware_flash.{key}")
    if settings["read_timeout_seconds"] > settings["query_timeout_seconds"]:
        raise ValueError("Serial read timeout must not exceed the query timeout")
    if not isinstance(settings["query_command"], str) or not re.fullmatch(
        r"[A-Z][A-Z0-9_]{0,63}", settings["query_command"]
    ):
        raise ValueError("Firmware query command must be a short uppercase token")


def firmware_identity(name, firmware, software):
    """Construct the compile-time identity that the running firmware must report."""
    identity = {
        "firmware_name": name,
        "firmware_version": firmware["version"],
        "protocol_version": firmware["protocol_version"],
        "git_commit": software.get("commit", "unknown"),
        "source_dirty": software.get("dirty", False),
    }
    return validate_identity(identity)


def validate_identity(identity):
    """Accept only the exact, bounded firmware identity JSON contract."""
    if not isinstance(identity, dict) or set(identity) != {
        "firmware_name",
        "firmware_version",
        "protocol_version",
        "git_commit",
        "source_dirty",
    }:
        raise ValueError("Firmware identity response has missing or unexpected fields")
    for key in ("firmware_name", "firmware_version", "git_commit"):
        value = identity[key]
        if (
            not isinstance(value, str)
            or not value.isascii()
            or not value.isprintable()
            or not 1 <= len(value) <= 255
        ):
            raise ValueError(f"Invalid firmware identity {key}")
    if (
        type(identity["protocol_version"]) is not int
        or not 1 <= identity["protocol_version"] < 2**32
    ):
        raise ValueError("Invalid firmware protocol version")
    if type(identity["source_dirty"]) is not bool:
        raise ValueError("Firmware source_dirty must be boolean")
    return identity


def artifact_checksums(directory):
    """Hash all compiler outputs; reject links and empty/non-firmware output."""
    directory = Path(directory)
    if not directory.is_dir() or directory.is_symlink():
        raise ValueError("Missing compiled artifact directory")
    hashes = {}
    for path in sorted(directory.rglob("*")):
        if path.is_symlink():
            raise ValueError("Compiled artifacts must not be symlinks")
        if path.is_file():
            hashes[path.relative_to(directory).as_posix()] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
    if not any(Path(name).suffix in (".hex", ".bin") for name in hashes):
        raise ValueError("Build contains no compiled firmware")
    return hashes
