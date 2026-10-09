"""Bounded serial I/O for the shared firmware identity protocol."""

import importlib
import json
import time

from ..firmware.identity import validate_identity


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
