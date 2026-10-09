"""Upload a validated build, verify its serial identity, and finalize both records."""

import argparse
import subprocess
import sys
import uuid
from pathlib import Path

from ...information.update import publish
from ...ui.navigation import confirm
from ...ui.progress import show_progress
from ..firmware.artifacts import artifact_checksums, load_build
from ..firmware.identity import identity_info
from ..settings import load_context
from .discovery import discover, recheck_target, selected_port
from .serial_protocol import load_serial, query_firmware
from .status import update_firmware_info, utc_now


class FlashError(RuntimeError):
    """A confirmed flashing attempt failed; its detailed log remains available."""

    def __init__(self, message, log_path):
        self.log_path = log_path
        super().__init__(f"{message}. Flash log: {log_path}")


def _upload_and_verify(command, address, query_settings, flash_settings, log_path, log):
    """Keep upload and identity results distinct, persisting each transition."""
    log["flash"]["status"] = "uploading"
    log["flash"]["upload_status"] = "in_progress"
    publish(log_path, log)
    with show_progress(f"Flashing {log['expected']['firmware_name']} to {address}"):
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=True,
            timeout=flash_settings["command_timeout_seconds"],
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
    if observed != log["expected"]:
        log["flash"]["verification_status"] = "mismatch"
        raise ValueError("Running firmware identity does not match the compiled build")
    log["flash"].update({"status": "verified", "verification_status": "verified"})


def _record_failure(log, error):
    """Preserve operation diagnostics without allowing cleanup to replace them."""
    log["flash"]["status"] = (
        "failed" if not isinstance(error, KeyboardInterrupt) else "interrupted"
    )
    log["flash"]["error"] = f"{type(error).__name__}: {error}"
    if isinstance(error, (subprocess.CalledProcessError, subprocess.TimeoutExpired)):
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


def _finalize_flash(root, report, address, log_path, log):
    """Attempt both record writes independently and return secondary errors."""
    log["flash"]["finished_at"] = utc_now()
    record = {
        "firmware_status": log["flash"]["verification_status"],
        "firmware_upload_status": log["flash"]["upload_status"],
        "firmware_checked_at": log["flash"]["finished_at"],
        "firmware_log": str(log_path),
    }
    if log["observed"]:
        record.update(identity_info(log["observed"]))
    attempted = log["flash"]["upload_status"] != "not_started"
    if not attempted:
        record = {
            key: record[key] for key in ("firmware_upload_status", "firmware_log")
        }
    errors = []
    # Write information even when logging fails, and logging even when information fails.
    try:
        update_firmware_info(root, report, address, record, replace_identity=attempted)
    except (OSError, ValueError, TypeError) as error:
        log["flash"]["system_info_error"] = str(error)
        errors.append(f"System information update failed: {error}")
    if errors:
        log["flash"]["status"] = "failed"
    try:
        publish(log_path, log)
    except (OSError, ValueError, TypeError) as error:
        errors.append(f"Final flash log write failed: {error}")
    return errors


def flash_firmware(artifacts, car_root=None, *, context=None):
    """Confirm, upload a compiled artifact snapshot, log, query, and publish identity.

    Return the detailed log path on verified success, None on refusal, or raise
    FlashError after a confirmed failure. Upload success alone is not verified
    firmware identity. This operation may reset/start hardware; use only with
    driving stopped, motors made safe, and other serial users closed.
    """
    context = context or load_context(car_root)
    root, flash_settings = context.root, context.flash_settings
    directory, manifest, query_settings = load_build(artifacts, root, context=context)
    load_serial()
    with show_progress("Detecting Arduino flash target"):
        report = discover(root, detailed=False, context=context)
    target = selected_port(report, manifest["board"]["fqbn"])
    address = target["port"]["address"]
    expected = manifest["firmware"]
    log_directory = context.directory(flash_settings["log_directory"])
    if not confirm(
        f"Flash {expected['firmware_name']} {expected['firmware_version']} to {address} "
        f"({manifest['board']['fqbn']})? This resets the board and may start motors. "
        "Confirm driving is stopped, motors are safe and other serial users are closed"
    ):
        return None
    log_directory.mkdir(parents=True, exist_ok=True)
    log_path = log_directory / f"{uuid.uuid4().hex}.toml"
    command = [
        *context.cli_command,
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
        f"{context.toolchain.discovery_timeout_seconds}s",
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
    try:
        publish(log_path, log)  # Fail closed if the detailed log cannot be created.
    except (OSError, ValueError, TypeError) as error:
        raise FlashError(f"Unable to create flash log: {error}", log_path) from error
    failure = None
    try:
        if artifact_checksums(directory) != manifest["artifacts"]:
            raise ValueError("Compiled artifacts changed after approval")
        with show_progress("Rechecking Arduino flash target"):
            rechecked = discover(root, detailed=False, context=context)
        recheck_target(rechecked, target, manifest["board"]["fqbn"])
        update_firmware_info(
            root,
            report,
            address,
            {"firmware_status": "unverified", "firmware_log": str(log_path)},
        )
        _upload_and_verify(
            command, address, query_settings, flash_settings, log_path, log
        )
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        RuntimeError,
        subprocess.SubprocessError,
        KeyboardInterrupt,
    ) as error:
        failure = error
        _record_failure(log, error)
    finalization_errors = _finalize_flash(root, report, address, log_path, log)
    if isinstance(failure, KeyboardInterrupt):
        for detail in finalization_errors:
            failure.add_note(detail)
        raise failure
    if failure is not None or finalization_errors:
        message = (
            str(failure) if failure is not None else "Unable to finalize flash records"
        )
        if finalization_errors:
            message += "; " + "; ".join(finalization_errors)
        raise FlashError(message, log_path) from failure
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
