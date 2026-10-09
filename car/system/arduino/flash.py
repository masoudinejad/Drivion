"""Flash an integrity-checked compiled build and verify its running identity."""

import argparse
import importlib
import json
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import tomllib

from ..configuration import arduino_toolchain_settings
from ..information.update import INFO_PATH, publish
from ..ui.navigation import confirm
from ..ui.progress import show_progress
from .compile import validate_compile_configuration
from .discover import compact_report, discover, retain_firmware_info
from .firmware import (
    artifact_checksums,
    validate_flash_configuration,
    validate_identity,
)


class FlashError(RuntimeError):
    """A confirmed flashing attempt failed; its detailed log remains available."""

    def __init__(self, message, log_path):
        self.log_path = log_path
        super().__init__(f"{message}. Flash log: {log_path}")


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def load_serial():
    """Preflight the serial dependency before any destructive upload."""
    try:
        return importlib.import_module("serial")
    except ImportError as error:
        raise RuntimeError(
            "Firmware verification requires the provisioned pyserial environment"
        ) from error


def query_firmware(address, settings, trace):
    """Query a newline-delimited JSON identity with bounded I/O and capture replies.

    Opening an AVR serial port may reset the board. The configured boot wait
    accommodates this before sending the query. The caller must stop driving
    and release the serial port before uploading or querying.
    """
    serial = load_serial()
    with serial.Serial(
        port=address,
        baudrate=settings["baud_rate"],
        timeout=settings["read_timeout_seconds"],
        write_timeout=settings["query_timeout_seconds"],
        exclusive=True,
    ) as connection:
        time.sleep(settings["boot_wait_seconds"])
        connection.reset_input_buffer()
        command = (settings["query_command"] + "\n").encode("ascii")
        trace["command"] = settings["query_command"]
        trace["responses"] = []
        if connection.write(command) != len(command):
            raise RuntimeError("Serial query was not written completely")
        deadline = time.monotonic() + settings["query_timeout_seconds"]
        received = 0
        pending = b""
        while time.monotonic() < deadline:
            connection.timeout = min(
                settings["read_timeout_seconds"], max(0, deadline - time.monotonic())
            )
            chunk = connection.read_until(
                b"\n", size=settings["max_response_bytes"] + 1
            )
            received += len(chunk)
            if chunk:
                trace["responses"].append(
                    chunk[: settings["max_response_bytes"]].decode(
                        "ascii", errors="replace"
                    )
                )
            if received > settings["max_response_bytes"]:
                raise ValueError(
                    "Firmware reply exceeded the configured response budget"
                )
            pending += chunk
            if not pending.endswith(b"\n"):
                continue
            line, pending = pending, b""
            try:
                value = json.loads(line)
            except (ValueError, UnicodeError):
                continue  # Ignore a bounded amount of startup/status chatter.
            return validate_identity(value)
    raise TimeoutError(
        "Arduino did not report its firmware identity before the deadline"
    )


def load_build(artifacts, root, config):
    """Read an immutable compile snapshot, never infer a version from live settings."""
    settings = config["firmware_compile"]
    validate_compile_configuration(settings, config["firmware"])
    directory = Path(artifacts)
    if directory.is_symlink():
        raise ValueError("Compiled build must not be a symlink")
    directory = directory.resolve(strict=True)
    builds = (root / settings["build_directory"]).resolve()
    if (
        not builds.is_relative_to(root)
        or not directory.is_relative_to(builds)
        or directory.name != "artifacts"
    ):
        raise ValueError("Select the artifact directory returned by compile_firmware")
    manifest_path = directory.parent / settings["manifest_filename"]
    if manifest_path.is_symlink():
        raise ValueError("Build manifest must not be a symlink")
    with manifest_path.open("rb") as stream:
        manifest = tomllib.load(stream)
    if set(manifest) != {"firmware", "board", "serial", "artifacts"}:
        raise ValueError("Invalid or incomplete compile manifest; compile again")
    identity = validate_identity(manifest["firmware"])
    if not isinstance(manifest["board"], dict) or set(manifest["board"]) != {"fqbn"}:
        raise ValueError("Build manifest must contain its target board")
    # Reuse the compilation contract for name, version and FQBN validation.
    validate_compile_configuration(
        settings,
        {
            identity["firmware_name"]: {
                "version": identity["firmware_version"],
                "protocol_version": identity["protocol_version"],
                "fqbn": manifest["board"]["fqbn"],
                "required_parameters": [],
                "parameters": {},
            }
        },
    )
    if not isinstance(manifest["serial"], dict) or set(manifest["serial"]) != {
        "baud_rate",
        "query_command",
    }:
        raise ValueError("Build manifest must contain its serial query contract")
    query_settings = {**config["firmware_flash"], **manifest["serial"]}
    validate_flash_configuration(query_settings)
    if artifact_checksums(directory) != manifest["artifacts"]:
        raise ValueError("Compiled artifacts changed since compilation; compile again")
    return directory, manifest, query_settings


def selected_port(report, fqbn):
    """Require one configured serial target and reject known board mismatches."""
    selection = report.get("selection", {})
    if selection.get("status") != "selected":
        raise ValueError(
            "No unique target; connect the Arduino and configure arduino.address"
        )
    matches = [
        item
        for item in report["ports"]
        if item["port"]["address"] == selection["address"]
    ]
    if len(matches) != 1 or matches[0]["port"].get("protocol") != "serial":
        raise ValueError("Flashing requires a uniquely selected serial port")
    candidates = {
        ":".join(board["fqbn"].split(":")[:3])
        for board in matches[0].get("matching_boards", [])
        if board.get("fqbn")
    }
    if candidates and ":".join(fqbn.split(":")[:3]) not in candidates:
        raise ValueError("Selected board candidates do not match the compiled target")
    return matches[0]


def update_firmware_info(root, report, address, record, *, replace_identity=True):
    """Replace only this target's cached firmware data and preserve other sections."""
    path = root / INFO_PATH
    sections = tomllib.loads(path.read_text()) if path.exists() else {}
    arduino = retain_firmware_info(compact_report(report), sections.get("arduino", {}))
    ports = arduino.get("ports", [arduino])
    for port in ports:
        if port.get("address") == address:
            if replace_identity:
                for key in list(port):
                    if key.startswith("firmware_"):
                        del port[key]
            port.update(record)
    sections["arduino"] = arduino
    publish(path, sections)


def flash_firmware(artifacts, car_root=None):
    """Confirm, upload a compiled artifact snapshot, log, query, and publish identity.

    Return the detailed log path on verified success, None on refusal, or raise
    FlashError after a confirmed failure. Upload success alone is not verified
    firmware identity. This operation may reset/start hardware; use only with
    driving stopped, motors made safe, and other serial users closed.
    """
    root = Path(car_root or Path(__file__).parents[2]).resolve()
    with (root / "config.toml").open("rb") as stream:
        config = tomllib.load(stream)
    validate_flash_configuration(config["firmware_flash"])
    directory, manifest, query_settings = load_build(artifacts, root, config)
    load_serial()
    tools = arduino_toolchain_settings(root)
    with show_progress("Detecting Arduino flash target"):
        report = discover(root)
    target = selected_port(report, manifest["board"]["fqbn"])
    address = target["port"]["address"]
    expected = manifest["firmware"]
    log_directory = (root / config["firmware_flash"]["log_directory"]).resolve()
    if (
        not log_directory.is_relative_to(root)
        or log_directory == root / "system/arduino"
    ):
        raise ValueError("Flash logs must be inside a dedicated Arduino subdirectory")
    for other in (
        (root / config["firmware_compile"]["build_directory"]).resolve(),
        (root / config["arduino"]["sketchbook_directory"]).resolve(),
    ):
        if log_directory.is_relative_to(other) or other.is_relative_to(log_directory):
            raise ValueError("Flash logs must not overlap sketches or builds")
    if not confirm(
        f"Flash {expected['firmware_name']} {expected['firmware_version']} to {address} "
        f"({manifest['board']['fqbn']})? This resets the board and may start motors. "
        "Confirm driving is stopped, motors are safe and other serial users are closed"
    ):
        return None
    log_directory.mkdir(parents=True, exist_ok=True)
    log_path = log_directory / f"{uuid.uuid4().hex}.toml"
    command = [
        tools.cli_executable_path,
        "--config-file",
        str(root.parent / tools.config_path),
        "upload",
        "--fqbn",
        manifest["board"]["fqbn"],
        "--port",
        address,
        "--input-dir",
        str(directory),
        "--verify",
        "--verbose",
        "--protocol",
        target["port"]["protocol"],
        "--discovery-timeout",
        f"{tools.discovery_timeout_seconds}s",
    ]
    log = {
        "flash": {
            "status": "preparing",
            "started_at": utc_now(),
            "address": address,
            "artifacts_directory": str(directory),
            "command": command,
            "upload_status": "not_started",
            "verification_status": "not_started",
        },
        "expected": expected,
        "observed": {},
        "query": {},
        "artifacts": manifest["artifacts"],
        "usb": target["port"].get("properties", {}),
    }
    publish(log_path, log)  # Fail closed if the detailed log cannot be created.
    observed = {}
    try:
        if artifact_checksums(directory) != manifest["artifacts"]:
            raise ValueError("Compiled artifacts changed after approval")
        with show_progress("Rechecking Arduino flash target"):
            rechecked = discover(root)
        current_target = selected_port(rechecked, manifest["board"]["fqbn"])
        if current_target["port"] != target["port"]:
            raise ValueError("Arduino target changed after approval; confirm again")
        update_firmware_info(
            root,
            report,
            address,
            {
                "firmware_status": "unverified",
                "firmware_log": str(log_path),
            },
        )
        log["flash"]["status"] = "uploading"
        log["flash"]["upload_status"] = "in_progress"
        publish(log_path, log)
        with show_progress(f"Flashing {expected['firmware_name']} to {address}"):
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=True,
                timeout=config["firmware_flash"]["command_timeout_seconds"],
            )
        log["flash"].update(
            {
                "upload_status": "ok",
                "stdout": result.stdout,
                "stderr": result.stderr,
                "returncode": result.returncode,
                "status": "querying",
                "verification_status": "in_progress",
            }
        )
        publish(log_path, log)
        with show_progress("Checking running Arduino firmware identity"):
            observed = query_firmware(address, query_settings, log["query"])
        log["observed"] = observed
        if observed != expected:
            log["flash"]["verification_status"] = "mismatch"
            raise ValueError(
                "Running firmware identity does not match the compiled build"
            )
        log["flash"].update({"status": "verified", "verification_status": "verified"})
    except (Exception, KeyboardInterrupt) as error:
        log["flash"]["status"] = (
            "failed" if not isinstance(error, KeyboardInterrupt) else "interrupted"
        )
        log["flash"]["error"] = f"{type(error).__name__}: {error}"
        if isinstance(
            error, (subprocess.CalledProcessError, subprocess.TimeoutExpired)
        ):
            for key in ("stdout", "stderr"):
                value = getattr(error, key, None)
                log["flash"][key] = (
                    value.decode(errors="replace")
                    if isinstance(value, bytes)
                    else value or ""
                )
            if isinstance(error, subprocess.CalledProcessError):
                log["flash"]["returncode"] = error.returncode
        if log["flash"]["upload_status"] == "in_progress":
            log["flash"]["upload_status"] = "failed"
        if log["flash"]["verification_status"] == "in_progress":
            log["flash"]["verification_status"] = "failed"
        if isinstance(error, KeyboardInterrupt):
            raise
        raise FlashError(str(error), log_path) from error
    finally:
        log["flash"]["finished_at"] = utc_now()
        publish(log_path, log)
        record = {
            "firmware_status": log["flash"]["verification_status"],
            "firmware_upload_status": log["flash"]["upload_status"],
            "firmware_checked_at": log["flash"]["finished_at"],
            "firmware_log": str(log_path),
        }
        if observed:
            record.update(
                {
                    "firmware_name": observed["firmware_name"],
                    "firmware_version": observed["firmware_version"],
                    "firmware_protocol_version": observed["protocol_version"],
                    "firmware_git_commit": observed["git_commit"],
                    "firmware_source_dirty": observed["source_dirty"],
                }
            )
        attempted = log["flash"]["upload_status"] != "not_started"
        if not attempted:
            record = {
                key: record[key] for key in ("firmware_upload_status", "firmware_log")
            }
        try:
            update_firmware_info(
                root, report, address, record, replace_identity=attempted
            )
        except (OSError, ValueError, TypeError) as error:
            log["flash"]["system_info_error"] = str(error)
            log["flash"]["status"] = "failed"
            publish(log_path, log)
            raise FlashError("Unable to update system information", log_path) from error
    return log_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "artifacts", type=Path, help="Artifact directory returned by compilation"
    )
    parser.add_argument("--car-root", type=Path)
    args = parser.parse_args()
    try:
        log_path = flash_firmware(args.artifacts, args.car_root)
        print(
            f"Firmware flashed and verified. Log: {log_path}"
            if log_path
            else "Flashing cancelled."
        )
        return 0 if log_path else 1
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError, TypeError, KeyError, RuntimeError) as error:
        print(f"Firmware flashing failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
