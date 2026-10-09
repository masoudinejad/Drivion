"""Compile a named firmware with TOML-derived parameters and identity, never upload."""

import argparse
import json
import math
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import tomllib

from ...information.update import INFO_PATH, publish
from ...ui.navigation import confirm
from ...ui.progress import show_progress
from ..settings import load_context, require_disjoint
from .artifacts import artifact_checksums
from .definitions import load_firmware
from .identity import firmware_identity


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
        "DRIVION_INFO_RESPONSE": response,
    }
    lines = ["// Generated from TOML; do not edit.", "#pragma once"]
    for key, value in {**metadata, **firmware["parameters"]}.items():
        lines.append(f"#define {key} {c_literal(value)}")
    return "\n".join(lines) + "\n"


def stage_library(sketch, car_root, settings):
    """Snapshot shared headers into Arduino's recursively compiled src directory."""
    root = Path(car_root).resolve()
    library = root / settings["library_directory"]
    if library.is_symlink() or not library.resolve().is_relative_to(root):
        raise ValueError("Firmware library must remain inside the car directory")
    if not (library / "DrivionFirmware.h").is_file():
        raise ValueError("Missing shared firmware identity library")
    if any(path.is_symlink() for path in library.rglob("*")):
        raise ValueError("Firmware library files must not be symlinks")
    require_disjoint(library.resolve(), Path(sketch).resolve())
    # Refuse collisions rather than replacing a sketch's own source files.
    shutil.copytree(library, Path(sketch) / "src/DrivionFirmware")


def compile_firmware(name, car_root=None, *, context=None):
    """Prepare an isolated sketch, confirm, and compile with visible progress.

    Return None on refusal; otherwise return the successful artifact directory.
    Failed builds retain CLI diagnostics through CalledProcessError. No source
    sketch is modified and no serial connection or upload is performed.
    """
    context = context or load_context(car_root)
    root = context.root
    settings, flash_settings = context.compile_settings, context.flash_settings
    firmware = load_firmware(name, root, context=context)
    sketchbook = context.directory(context.runtime.sketchbook_directory)
    source = (sketchbook / name).resolve()
    builds = context.directory(settings["build_directory"])
    if not source.is_relative_to(sketchbook):
        raise ValueError("Firmware source must remain inside the sketchbook")
    if not (source / f"{name}.ino").is_file():
        raise ValueError(f"Missing primary sketch: {source / f'{name}.ino'}")
    if any(path.is_symlink() for path in source.rglob("*")):
        raise ValueError("Sketch files must not be symlinks")
    if (source / settings["header_filename"]).exists():
        raise ValueError("Generated header must not exist in the source sketch")
    info = root / INFO_PATH
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
        stage_library(staged, root, settings)
        (staged / settings["header_filename"]).write_text(header, encoding="utf-8")
        result = subprocess.run(
            [
                *context.cli_command,
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
