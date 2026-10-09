"""Discover connected ports and board specifications without flashing hardware."""

import argparse
import json
import subprocess
import sys
from pathlib import Path

import tomllib

from ..configuration import arduino_settings, arduino_toolchain_settings


def _without_nulls(value):
    """Retain CLI metadata while removing JSON nulls unsupported by TOML."""
    if isinstance(value, dict):
        return {
            key: _without_nulls(item) for key, item in value.items() if item is not None
        }
    if isinstance(value, list):
        return [_without_nulls(item) for item in value if item is not None]
    return value


def _validate_ports(value):
    """Validate the documented Arduino CLI board-list structure."""
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ValueError("Arduino CLI detected_ports must be a list of objects")
    for detected in value:
        port = detected.get("port")
        candidates = detected.get("matching_boards", [])
        if not isinstance(port, dict) or not isinstance(port.get("address"), str):
            raise TypeError("Every detected Arduino port must have a string address")
        if not isinstance(candidates, list) or any(
            not isinstance(candidate, dict) for candidate in candidates
        ):
            raise ValueError("Arduino matching_boards must be a list of objects")
        properties = port.get("properties", {})
        if not isinstance(properties, dict):
            raise TypeError("Arduino port properties must be an object")
        for candidate in candidates:
            for key in ("name", "fqbn"):
                if key in candidate and not isinstance(candidate[key], str):
                    raise ValueError(f"Arduino board {key} must be a string")
    return value


def _select_address(ports, configured):
    addresses = [detected["port"]["address"] for detected in ports]
    if configured == "auto":
        if len(addresses) == 1:
            return {"status": "selected", "address": addresses[0]}
        return {
            "status": "none" if not addresses else "ambiguous",
            "configured_address": configured,
        }
    if addresses.count(configured) == 1:
        return {"status": "selected", "address": configured}
    return {"status": "missing", "configured_address": configured}


def discover(car_root, config_root=None):
    """Return observed ports, candidate boards, and installed core metadata.

    Board details describe a core's available options, not measured processor or
    bootloader settings. Multiple matches remain candidates; unknown USB serial
    adapters remain unidentified. Individual detail failures retain port data.
    """
    car_root = Path(car_root)
    config_root = Path(config_root) if config_root is not None else car_root
    runtime = arduino_settings(config_root)
    toolchain = arduino_toolchain_settings(config_root)
    wait = toolchain.discovery_timeout_seconds
    timeout = toolchain.command_timeout_seconds
    cli_config = (
        Path(toolchain.service_config_path)
        if config_root != car_root
        else car_root.resolve().parent / toolchain.config_path
    )
    command = [
        toolchain.cli_executable_path,
        "--config-file",
        str(cli_config),
        "--json",
    ]

    def query(*arguments):
        result = subprocess.run(
            command + list(arguments),
            capture_output=True,
            text=True,
            check=True,
            timeout=timeout,
        )
        value = json.loads(result.stdout)
        if not isinstance(value, dict):
            raise TypeError("Arduino CLI JSON response must be an object")
        return _without_nulls(value)

    errors = (OSError, subprocess.SubprocessError, ValueError, TypeError)
    try:
        listing = query("board", "list", "--discovery-timeout", f"{wait}s")
        ports = _validate_ports(listing.get("detected_ports", []))
    except errors as error:
        return {"status": "error", "error": str(error), "ports": []}
    selection = _select_address(ports, runtime.address)
    report = {"status": "ok", "selection": selection, "ports": ports}
    if selection["status"] in ("ambiguous", "missing"):
        report["status"] = "partial"
    try:
        report["cores"] = query("core", "list")
    except errors as error:
        report["core_error"] = str(error)
        report["status"] = "partial"
    details = {}
    for port in ports:
        candidates = port.get("matching_boards", [])
        port["identification"] = "unidentified" if not candidates else "candidate"
        for board in candidates:
            fqbn = board.get("fqbn")
            if not fqbn:
                continue
            if fqbn not in details:
                try:
                    details[fqbn] = query(
                        "board",
                        "details",
                        "--fqbn",
                        fqbn,
                        "--full",
                        "--list-programmers",
                    )
                except errors as error:
                    details[fqbn] = {"error": str(error)}
                    report["status"] = "partial"
            board["specifications"] = details[fqbn]
    return report


def compact_report(report):
    """Flatten a single device; retain all entries when multiple ports exist."""
    compact = {
        key: report[key]
        for key in ("status", "error", "core_error", "selection")
        if key in report
    }
    compact["ports"] = []
    for detected in report.get("ports", []):
        port = detected.get("port", {})
        properties = port.get("properties", {})
        item = {
            "identification": detected.get("identification", "unidentified"),
            "matching_boards": [],
        }
        item.update(
            {
                key: port[key]
                for key in ("address", "protocol", "hardware_id")
                if key in port
            }
        )
        item.update(
            {
                key: properties[key]
                for key in ("serialNumber", "vid", "pid")
                if key in properties
            }
        )
        for board in detected.get("matching_boards", []):
            candidate = {key: board[key] for key in ("name", "fqbn") if key in board}
            error = board.get("specifications", {}).get("error")
            if error:
                candidate["error"] = error
            item["matching_boards"].append(candidate)
        compact["ports"].append(item)
    if len(compact["ports"]) == 1:
        compact.update(compact.pop("ports")[0])
    return compact


def format_summary(report):
    """Show observed identity and errors without dumping core specifications."""
    lines = [f"Discovery: {report['status']}"]
    for key in ("error", "core_error"):
        if report.get(key):
            lines.append(f"Error: {report[key]}")
    selection = report.get("selection", {})
    if selection.get("status") == "selected":
        lines.append(f"Selected address: {selection['address']}")
    elif selection.get("status") == "ambiguous":
        lines.append("Address selection: multiple ports; configure arduino.address")
    elif selection.get("status") == "missing":
        lines.append(
            f"Address selection: {selection['configured_address']} is not connected"
        )
    ports = report.get("ports", [])
    if not ports and report["status"] == "ok":
        lines.append("No connected ports detected.")
    for detected in ports:
        port = detected.get("port", {})
        properties = port.get("properties", {})
        lines.append(f"\nPort: {port.get('address', 'unknown')}")
        lines.append(
            f"USB serial number: {properties.get('serialNumber') or 'not provided'}"
        )
        lines.append(
            f"USB VID/PID: {properties.get('vid') or 'unknown'}/{properties.get('pid') or 'unknown'}"
        )
        candidates = detected.get("matching_boards", [])
        if not candidates:
            lines.append("Board: unidentified")
        for board in candidates:
            lines.append(f"Board candidate: {board.get('name', 'unknown')}")
            lines.append(f"FQBN: {board.get('fqbn') or 'not provided'}")
            error = board.get("specifications", {}).get("error")
            if error:
                lines.append(f"Details error: {error}")
    return "\n".join(lines)


def retain_firmware_info(current, previous):
    """Preserve last-observed firmware only for the same USB identity and address.

    Discovery does not open/reset the board to re-query firmware. Cached fields
    keep their observation timestamp; a previous verified result becomes
    last_verified on refresh. Adapters without serial numbers cannot distinguish
    replacement boards sharing VID/PID and address, so this is historical data.
    """
    previous_ports = previous.get("ports", [previous])
    for port in current.get("ports", [current]):
        matches = [
            old
            for old in previous_ports
            if port.get("address")
            and all(
                port.get(key) == old.get(key)
                for key in ("address", "serialNumber", "vid", "pid")
            )
        ]
        if len(matches) == 1:
            port.update(
                {
                    key: value
                    for key, value in matches[0].items()
                    if key.startswith("firmware_")
                }
            )
            if port.get("firmware_status") == "verified":
                port["firmware_status"] = "last_verified"
    return current


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--car-root", type=Path, required=True)
    parser.add_argument(
        "--config-root",
        type=Path,
        help="Root containing protected config.toml and system/pyproject.toml",
    )
    parser.add_argument(
        "--verbose", action="store_true", help="Print the full JSON report"
    )
    args = parser.parse_args(argv)
    # Import here to keep discovery usable by the information collector.
    from ..information.update import INFO_PATH, publish

    try:
        path = args.car_root / INFO_PATH
        sections = tomllib.loads(path.read_text()) if path.exists() else {}
        report = discover(args.car_root, args.config_root)
        sections["arduino"] = retain_firmware_info(
            compact_report(report), sections.get("arduino", {})
        )
        publish(path, sections)
        print(json.dumps(report, indent=2) if args.verbose else format_summary(report))
        return 0 if sections["arduino"]["status"] == "ok" else 1
    except (KeyError, OSError, TypeError, ValueError) as error:
        print(f"Arduino discovery error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
