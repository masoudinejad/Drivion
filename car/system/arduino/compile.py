"""Compile a named firmware with TOML-derived parameters and identity, never upload."""

import argparse
import json
import math
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import tomllib

from ..configuration import arduino_settings, arduino_toolchain_settings
from ..ui.navigation import confirm
from ..ui.progress import show_progress
from .firmware import (
    artifact_checksums,
    firmware_identity,
    validate_flash_configuration,
)


def validate_compile_configuration(settings, firmwares):
    """Validate the shared TOML contract without requiring the car environment."""
    if not isinstance(settings, dict) or not isinstance(firmwares, dict):
        raise TypeError("Firmware configuration must contain TOML tables")
    if set(settings) != {
        "build_directory",
        "header_filename",
        "manifest_filename",
        "command_timeout_seconds",
    }:
        raise ValueError("Configure exactly the supported firmware_compile settings")
    if not isinstance(settings["build_directory"], str):
        raise TypeError("Build directory must be a relative path string")
    path = Path(settings["build_directory"])
    if (
        path.is_absolute()
        or ".." in path.parts
        or not path.is_relative_to("system/arduino")
    ):
        raise ValueError("Build directory must be inside system/arduino")
    if not isinstance(settings["header_filename"], str) or not re.fullmatch(
        r"[A-Za-z][A-Za-z0-9_]*\.h", settings["header_filename"]
    ):
        raise ValueError("Configure a safe generated header filename")
    timeout = settings["command_timeout_seconds"]
    if type(timeout) is not int or not 1 <= timeout <= 3600:
        raise ValueError("Compile timeout must be between 1 and 3600 seconds")
    if not isinstance(settings["manifest_filename"], str) or not re.fullmatch(
        r"[A-Za-z][A-Za-z0-9_]*\.toml", settings["manifest_filename"]
    ):
        raise ValueError("Configure a safe build manifest filename")
    for name, firmware in firmwares.items():
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", name):
            raise ValueError("Firmware names must be safe identifiers")
        if not isinstance(firmware, dict) or set(firmware) != {
            "version",
            "protocol_version",
            "fqbn",
            "required_parameters",
            "parameters",
        }:
            raise ValueError(f"Configure exactly the supported fields for {name}")
        if (
            not isinstance(firmware["version"], str)
            or not firmware["version"].isascii()
            or not firmware["version"].isprintable()
            or not firmware["version"]
        ):
            raise ValueError("Firmware version must be non-empty printable text")
        if (
            type(firmware["protocol_version"]) is not int
            or not 1 <= firmware["protocol_version"] < 2**32
        ):
            raise ValueError("Protocol version must be a positive integer")
        if not isinstance(firmware["fqbn"], str) or not re.fullmatch(
            r"[A-Za-z0-9_-]+:[A-Za-z0-9_-]+:[A-Za-z0-9_-]+(?::[A-Za-z0-9_=,.-]+)?",
            firmware["fqbn"],
        ):
            raise ValueError("Configure an explicit board FQBN")
        required = firmware["required_parameters"]
        values = firmware["parameters"]
        if (
            not isinstance(required, list)
            or not isinstance(values, dict)
            or any(
                not isinstance(key, str)
                or not re.fullmatch(r"[A-Z][A-Z0-9_]*", key)
                or key.startswith("DRIVION_")
                for key in required
            )
        ):
            raise ValueError(
                "Parameters must be uppercase identifiers, excluding DRIVION_ names"
            )
        if len(set(required)) != len(required) or set(required) != set(values):
            raise ValueError(
                f"Parameters for {name} must exactly match required_parameters"
            )
        for value in values.values():
            c_literal(value)


def c_literal(value):
    """Encode supported scalar TOML values as injection-safe AVR C++ literals."""
    if type(value) is bool:
        return str(value).lower()
    if type(value) is int and -(2**31) <= value < 2**32:
        return f"({value}L)" if value < 0 else f"{value}UL"
    if type(value) is float and math.isfinite(value) and abs(value) <= 3.402823466e38:
        return repr(value) + "f"
    if isinstance(value, str) and value.isascii() and "\x00" not in value:
        # Octal escapes avoid invalid low-codepoint C++ universal escapes and
        # preprocessor trigraphs; fixed width prevents consuming the next digit.
        escaped = "".join(
            character
            if 32 <= ord(character) < 127 and character not in '\\"?'
            else f"\\{ord(character):03o}"
            for character in value
        )
        return f'"{escaped}"'
    raise ValueError(
        "Firmware parameters must be AVR-range integers, finite floats, booleans or ASCII strings"
    )


def render_header(name, firmware, software, flash_settings):
    """Render a consistent header; deployment identity is not firmware version."""
    identity = firmware_identity(name, firmware, software)
    response = json.dumps(identity, separators=(",", ":"))
    if len(response.encode("ascii")) + 2 > flash_settings["max_response_bytes"]:
        raise ValueError(
            "Firmware identity exceeds the configured serial response limit"
        )
    metadata = {
        "DRIVION_FIRMWARE_NAME": name,
        "DRIVION_FIRMWARE_VERSION": firmware["version"],
        "DRIVION_PROTOCOL_VERSION": firmware["protocol_version"],
        "DRIVION_GIT_COMMIT": software.get("commit", "unknown"),
        "DRIVION_SOURCE_DIRTY": software.get("dirty", False),
        "DRIVION_SERIAL_BAUD_RATE": flash_settings["baud_rate"],
        "DRIVION_INFO_COMMAND": flash_settings["query_command"],
    }
    lines = ["// Generated from TOML; do not edit.", "#pragma once"]
    for key, value in {**metadata, **firmware["parameters"]}.items():
        lines.append(f"#define {key} {c_literal(value)}")
    # Call from the sketch's existing command dispatcher; never swallow motor
    # commands by creating a separate reader competing for the serial stream.
    lines.extend(
        [
            "#include <Arduino.h>",
            "#include <string.h>",
            "inline bool drivionHandleInfo(const char *command) {",
            "  if (strcmp(command, DRIVION_INFO_COMMAND) != 0) return false;",
            f"  Serial.println(F({c_literal(response)}));",
            "  return true;",
            "}",
        ]
    )
    return "\n".join(lines) + "\n"


def compile_firmware(name, car_root=None):
    """Prepare an isolated sketch, confirm, and compile with visible progress.

    Return None on refusal; otherwise return the successful artifact directory.
    Failed builds retain CLI diagnostics through CalledProcessError. No source
    sketch is modified and no serial connection or upload is performed.
    """
    root = Path(car_root or Path(__file__).parents[2]).resolve()
    with (root / "config.toml").open("rb") as stream:
        config = tomllib.load(stream)
    settings, firmwares = config["firmware_compile"], config["firmware"]
    validate_compile_configuration(settings, firmwares)
    flash_settings = config["firmware_flash"]
    validate_flash_configuration(flash_settings)
    if name not in firmwares:
        raise ValueError(f"Unknown firmware: {name}")
    firmware = firmwares[name]
    runtime, tools = arduino_settings(root), arduino_toolchain_settings(root)
    sketchbook = (root / runtime.sketchbook_directory).resolve()
    source = (sketchbook / name).resolve()
    builds = (root / settings["build_directory"]).resolve()
    if (
        not sketchbook.is_relative_to(root)
        or not source.is_relative_to(sketchbook)
        or not builds.is_relative_to(root)
    ):
        raise ValueError("Firmware paths must remain inside the car directory")
    if (
        builds == sketchbook
        or builds.is_relative_to(sketchbook)
        or sketchbook.is_relative_to(builds)
    ):
        raise ValueError("Build directory and sketchbook must not overlap")
    if not (source / f"{name}.ino").is_file():
        raise ValueError(f"Missing primary sketch: {source / f'{name}.ino'}")
    if any(path.is_symlink() for path in source.rglob("*")):
        raise ValueError("Sketch files must not be symlinks")
    if (source / settings["header_filename"]).exists():
        raise ValueError("Generated header must not exist in the source sketch")
    info = root / "system/info.toml"
    software = {}
    if info.is_file():
        with info.open("rb") as stream:
            software = tomllib.load(stream).get("software", {})
    header = render_header(name, firmware, software, flash_settings)
    if not confirm(
        f"Compile {name} {firmware['version']} for {firmware['fqbn']}? (No upload)"
    ):
        return None
    builds.mkdir(parents=True, exist_ok=True)
    destination = Path(tempfile.mkdtemp(prefix=f"{name}-", dir=builds))
    with show_progress(f"Compiling {name} {firmware['version']}"):
        staged = destination / name
        shutil.copytree(source, staged)
        (staged / settings["header_filename"]).write_text(header, encoding="utf-8")
        result = subprocess.run(
            [
                tools.cli_executable_path,
                "--config-file",
                str(root.parent / tools.config_path),
                "compile",
                "--fqbn",
                firmware["fqbn"],
                "--output-dir",
                str(destination / "artifacts"),
                str(staged),
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=settings["command_timeout_seconds"],
        )
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    # Publish only after a successful compile with real output. Flashing reads
    # this snapshot, not the potentially changed live firmware configuration.
    from ..information.update import publish

    manifest = {
        "firmware": firmware_identity(name, firmware, software),
        "board": {"fqbn": firmware["fqbn"]},
        "serial": {key: flash_settings[key] for key in ("baud_rate", "query_command")},
        "artifacts": artifact_checksums(destination / "artifacts"),
    }
    publish(destination / settings["manifest_filename"], manifest)
    return destination / "artifacts"


def main():
    """Interactive command-line entry point; approval cannot be bypassed."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("firmware", help="Firmware name registered in config.toml")
    parser.add_argument("--car-root", type=Path)
    args = parser.parse_args()
    try:
        artifacts = compile_firmware(args.firmware, args.car_root)
        print(
            f"Compiled firmware: {artifacts}" if artifacts else "Compilation cancelled."
        )
        return 0 if artifacts else 1
    except KeyboardInterrupt:
        return 130
    except subprocess.CalledProcessError as error:
        print(error.stdout or "", end="", file=sys.stderr)
        print(error.stderr or str(error), file=sys.stderr)
        return 2
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        RuntimeError,
        subprocess.TimeoutExpired,
    ) as error:
        print(f"Firmware compilation failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
