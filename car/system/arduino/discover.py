"""Discover connected ports and board specifications without flashing hardware."""

import argparse
import json
import subprocess
from pathlib import Path

import tomllib

from ..configuration import arduino_settings


def _without_nulls(value):
    """Retain CLI metadata while removing JSON nulls unsupported by TOML."""
    if isinstance(value, dict):
        return {
            key: _without_nulls(item) for key, item in value.items() if item is not None
        }
    if isinstance(value, list):
        return [_without_nulls(item) for item in value if item is not None]
    return value


def discover(car_root):
    """Return observed ports, candidate boards, and installed core metadata.

    Board details describe a core's available options, not measured processor or
    bootloader settings. Multiple matches remain candidates; unknown USB serial
    adapters remain unidentified. Individual detail failures retain port data.
    """
    car_root = Path(car_root)
    settings = arduino_settings(car_root)
    with (car_root / "config.toml").open("rb") as stream:
        discovery = tomllib.load(stream)["arduino"]["discovery"]
    wait = discovery["discovery_timeout_seconds"]
    timeout = discovery["command_timeout_seconds"]
    if (
        type(wait) is not int
        or type(timeout) is not int
        or not 1 <= wait <= 300
        or not wait < timeout <= 600
    ):
        raise ValueError("Configure valid arduino.discovery timeouts")
    command = [
        settings.cli_executable_path,
        "--config-file",
        str(car_root.resolve().parent / settings.config_path),
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
        ports = listing.get("detected_ports", [])
        if not isinstance(ports, list) or any(
            not isinstance(port, dict) for port in ports
        ):
            raise ValueError("Arduino CLI detected_ports must be a list of objects")
    except errors as error:
        return {"status": "error", "error": str(error), "ports": []}
    report = {"status": "ok", "ports": ports}
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
        key: report[key] for key in ("status", "error", "core_error") if key in report
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


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--car-root", type=Path, required=True)
    parser.add_argument(
        "--verbose", action="store_true", help="Print the full JSON report"
    )
    args = parser.parse_args(argv)
    # Import here to keep discovery usable by the information collector.
    from ..information.update import INFO_PATH, publish

    path = args.car_root / INFO_PATH
    sections = tomllib.loads(path.read_text()) if path.exists() else {}
    report = discover(args.car_root)
    sections["arduino"] = compact_report(report)
    publish(path, sections)
    print(json.dumps(report, indent=2) if args.verbose else format_summary(report))
    return 0 if sections["arduino"]["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
