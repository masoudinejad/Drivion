"""Validated Arduino operation settings loaded once per firmware workflow."""

import math
import re
from dataclasses import dataclass
from pathlib import Path

import tomllib

from ..configuration import (
    ArduinoSettings,
    ArduinoToolchainSettings,
    arduino_settings,
    arduino_toolchain_settings,
)


def validate_directory(value, label):
    """Require a dedicated relative Arduino directory, shared with sync tooling."""
    if not isinstance(value, str):
        raise TypeError(f"{label} must be a path string")
    path = Path(value)
    if (
        "\\" in value
        or path.is_absolute()
        or ".." in path.parts
        or path == Path("system/arduino")
        or not path.is_relative_to("system/arduino")
    ):
        raise ValueError(
            f"{label} must be inside a dedicated system/arduino subdirectory"
        )
    return path


def require_disjoint(first, second):
    """Reject recursive copying and source/output directory collisions."""
    if first.is_relative_to(second) or second.is_relative_to(first):
        raise ValueError(f"Arduino directories must not overlap: {first} and {second}")


@dataclass(frozen=True)
class FirmwareContext:
    """One validated configuration snapshot for a compile/check/flash workflow."""

    root: Path
    runtime: ArduinoSettings
    toolchain: ArduinoToolchainSettings
    compile_settings: dict
    flash_settings: dict
    firmware_defaults: dict

    @property
    def cli_command(self):
        return [
            self.toolchain.cli_executable_path,
            "--config-file",
            str(self.root.parent / self.toolchain.config_path),
        ]

    def directory(self, value):
        """Resolve a configured path without allowing symlink escapes."""
        path = (self.root / value).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("Firmware paths must remain inside the car directory")
        return path


def load_context(car_root=None):
    """Read each central TOML once; validate the complete operation layout."""
    root = Path(car_root or Path(__file__).parents[2]).resolve()
    with (root / "config.toml").open("rb") as stream:
        runtime = tomllib.load(stream)
    with (root / "system/pyproject.toml").open("rb") as stream:
        tools = tomllib.load(stream)["tool"]["drivion"]
    if not isinstance(runtime["firmware"], dict):
        raise TypeError("Firmware defaults must be a TOML table")
    compile_settings = tools["firmware_compile"]
    flash_settings = serial_settings(tools["firmware_flash"], runtime)
    validate_compile_configuration(compile_settings)
    validate_flash_configuration(flash_settings)
    context = FirmwareContext(
        root,
        arduino_settings(root, values=runtime["arduino"]),
        arduino_toolchain_settings(root, values=tools["arduino"]),
        compile_settings,
        flash_settings,
        runtime["firmware"],
    )
    directories = [
        context.directory(value)
        for value in (
            context.runtime.sketchbook_directory,
            context.compile_settings["library_directory"],
            context.compile_settings["build_directory"],
            context.flash_settings["log_directory"],
        )
    ]
    for index, first in enumerate(directories):
        for second in directories[index + 1 :]:
            require_disjoint(first, second)
    return context


def tool_settings(car_root, kind):
    """Read a tool table, merging the central serial baud for flash/check tools."""
    if kind not in ("compile", "flash"):
        raise ValueError("Unsupported firmware tool settings")
    with (Path(car_root) / "system/pyproject.toml").open("rb") as stream:
        settings = tomllib.load(stream)["tool"]["drivion"][f"firmware_{kind}"]
    if kind == "flash":
        with (Path(car_root) / "config.toml").open("rb") as stream:
            settings = serial_settings(settings, tomllib.load(stream))
    validator = (
        validate_compile_configuration
        if kind == "compile"
        else validate_flash_configuration
    )
    validator(settings)
    return settings


def serial_settings(settings, runtime):
    """Use the central link baud for firmware generation, checking and runtime."""
    if "baud_rate" in settings:
        raise ValueError("Move firmware_flash.baud_rate to communication.baud_rate")
    baud = runtime["communication"]["baud_rate"]
    if type(baud) is not int or not 1 <= baud <= 4000000:
        raise ValueError("Configure a valid communication.baud_rate")
    return {**settings, "baud_rate": baud}


def validate_compile_configuration(settings):
    """Validate system tool settings, never user firmware parameter declarations."""
    if not isinstance(settings, dict) or set(settings) != {
        "build_directory",
        "library_directory",
        "header_filename",
        "manifest_filename",
        "definition_filename",
        "command_timeout_seconds",
    }:
        raise ValueError(
            "Configure exactly the supported tool.drivion.firmware_compile settings"
        )
    for key in ("build_directory", "library_directory"):
        validate_directory(settings[key], key)
    require_disjoint(
        Path(settings["build_directory"]), Path(settings["library_directory"])
    )
    for key, extension in (
        ("header_filename", "h"),
        ("manifest_filename", "toml"),
        ("definition_filename", "toml"),
    ):
        if not isinstance(settings[key], str) or not re.fullmatch(
            r"[A-Za-z][A-Za-z0-9_]*\." + extension, settings[key]
        ):
            raise ValueError(f"Configure a safe {key}")
    if (
        type(settings["command_timeout_seconds"]) is not int
        or not 1 <= settings["command_timeout_seconds"] <= 3600
    ):
        raise ValueError("Compile timeout must be between 1 and 3600 seconds")


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
    validate_directory(settings["log_directory"], "log_directory")
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
