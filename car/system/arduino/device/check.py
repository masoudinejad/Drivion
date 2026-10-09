"""Read the running Arduino firmware identity without compiling or uploading."""

import argparse
import json
import sys
from pathlib import Path

from ...ui.navigation import confirm
from ...ui.progress import show_progress
from ..firmware.identity import identity_info
from ..settings import load_context
from .discovery import discover, recheck_target, selected_port
from .serial_protocol import load_serial, query_firmware
from .status import update_firmware_info, utc_now


def check_firmware(car_root=None):
    """Confirm a serial query and return observed identity or a failure report.

    Return None on refusal, otherwise a dict with status, address, checked_at,
    query transcript, and either firmware identity or error. Preflight/selection
    errors raise without opening serial or changing information. Query failures
    clear stale identity for this port, while keeping its previous flash log and
    upload status. Other ports and information sections remain unchanged.

    A reported identity is not verification against a compiled artifact. Serial
    settings come from system tool metadata TOML and must match the running
    sketch. Opening serial may reset/start the board: stop driving, make motors
    safe, close other serial users, and serialize management operations first.
    """
    context = load_context(car_root)
    root, settings = context.root, context.flash_settings
    load_serial()
    with show_progress("Detecting Arduino firmware-check target"):
        discovery = discover(root, detailed=False, context=context)
    target = selected_port(discovery)
    address = target["port"]["address"]
    if not confirm(
        f"Check running firmware on {address}? Opening serial may reset the board. "
        "Confirm driving is stopped, motors are safe and other serial users are closed"
    ):
        return None
    with show_progress("Rechecking Arduino firmware-check target"):
        current = discover(root, detailed=False, context=context)
    recheck_target(current, target)
    report = {"status": "error", "address": address, "query": {}}
    record = {"firmware_status": "error"}
    try:
        with show_progress("Reading running Arduino firmware identity"):
            observed = query_firmware(address, settings, report["query"])
        record.update(identity_info(observed))
        report.update({"status": "ok", "firmware": observed})
        record["firmware_status"] = "reported"
    except (OSError, RuntimeError, ValueError, TypeError) as error:
        report["error"] = f"{type(error).__name__}: {error}"
        record["firmware_check_error"] = report["error"]
    except KeyboardInterrupt:
        record["firmware_status"] = "interrupted"
        record["firmware_check_error"] = "Firmware check interrupted"
        raise
    finally:
        report["checked_at"] = utc_now()
        record["firmware_checked_at"] = report["checked_at"]
        update_firmware_info(
            root, current, address, record, preserve_flash_history=True
        )
    return report


def format_summary(report):
    """Show a concise firmware identity, never dump the serial transcript."""
    lines = [f"Firmware check: {report['status']}", f"Port: {report['address']}"]
    if "error" in report:
        lines.append(f"Error: {report['error']}")
    else:
        firmware = report["firmware"]
        lines.extend(
            [
                f"Firmware: {firmware['firmware_name']}",
                f"Version: {firmware['firmware_version']}",
                f"Protocol version: {firmware['protocol_version']}",
                f"Git commit: {firmware['git_commit']}",
                f"Source dirty: {str(firmware['source_dirty']).lower()}",
            ]
        )
    lines.append(f"Checked at: {report['checked_at']}")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--car-root", type=Path)
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Include the serial query transcript as JSON",
    )
    args = parser.parse_args(argv)
    try:
        report = check_firmware(args.car_root)
        if report is None:
            print("Firmware check cancelled.")
            return 1
        print(json.dumps(report, indent=2) if args.verbose else format_summary(report))
        return 0 if report["status"] == "ok" else 1
    except KeyboardInterrupt:
        return 130
    except (OSError, RuntimeError, ValueError, TypeError, KeyError) as error:
        print(f"Firmware check failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
