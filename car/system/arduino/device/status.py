"""Persist timestamped firmware observations without losing other information."""

from datetime import datetime, timezone

import tomllib

from ...information.update import INFO_PATH, publish
from .discovery import compact_report, retain_firmware_info


def utc_now():
    """Timestamp an observation in UTC using ISO 8601."""
    return datetime.now(timezone.utc).isoformat()


def update_firmware_info(
    root,
    report,
    address,
    record,
    *,
    replace_identity=True,
    preserve_flash_history=False,
):
    """Replace this port's cached identity, optionally keeping last-flash provenance."""
    path = root / INFO_PATH
    sections = tomllib.loads(path.read_text()) if path.exists() else {}
    arduino = retain_firmware_info(compact_report(report), sections.get("arduino", {}))
    ports = arduino.get("ports", [arduino])
    for port in ports:
        if port.get("address") == address:
            if replace_identity:
                for key in list(port):
                    if key.startswith("firmware_") and not (
                        preserve_flash_history
                        and key in ("firmware_log", "firmware_upload_status")
                    ):
                        del port[key]
            port.update(record)
    sections["arduino"] = arduino
    publish(path, sections)
