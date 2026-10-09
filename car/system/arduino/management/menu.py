"""Interactive device identification and configuration for system management."""

from pathlib import Path

from ...information.view import render_info
from ...ui.navigation import select_item, show_page
from ...ui.progress import run_background
from ..device.check import check_firmware, format_summary
from ..device.discovery import discover
from .workflow import change_firmware


def identify_device(car_root, *, select=select_item, display=show_page):
    """Discover ports, let the user choose one, and persist its runtime address.

    USB metadata and board candidates describe observations, not user settings.
    FQBN/bootloader selection belongs to each registered firmware; identification
    must not guess those settings for unidentified or ambiguous USB adapters.
    """
    # Keep read-only management usable without the configuration dependencies.
    try:
        from car.src.config import update_config
    except ImportError as error:
        raise RuntimeError(
            "Run management with the configured car Python environment "
            "to use the configuration modifier."
        ) from error

    root = Path(car_root)
    report = run_background(
        "Identifying connected Arduino devices", discover, root, detailed=False
    )
    ports = report.get("ports", [])
    if not ports:
        display(
            "Arduino identification",
            report.get("error")
            or "No connected devices detected. Connect a board and try again.",
        )
        return
    labels = []
    for detected in ports:
        port = detected["port"]
        boards = detected.get("matching_boards", [])
        names = ", ".join(board.get("name", "Unknown board") for board in boards)
        label = f"{port['address']} — {names or 'Unidentified board'}"
        # Device-provided text must not insert terminal control sequences.
        labels.append("".join(char if char.isprintable() else " " for char in label))
    selected = select("Select Arduino device to save", labels)
    if selected is None:
        return
    if not 0 <= selected < len(ports):
        raise ValueError("Invalid Arduino device selection")
    device = ports[selected]
    address = device["port"]["address"]
    # Recheck connection before writing; cancellation and failed scans never save.
    current = run_background(
        "Checking selected Arduino device", discover, root, detailed=False
    )
    matches = [
        item
        for item in current.get("ports", [])
        if item["port"]["address"] == address
        and item["port"].get("properties", {}) == device["port"].get("properties", {})
    ]
    if len(matches) != 1:
        raise RuntimeError(
            "Selected device disconnected or changed. Identify devices again."
        )
    update_config("arduino.address", address, root / "config.toml")
    display(
        "Arduino device selected",
        f"Saved arduino.address = {address}\n\n"
        + render_info({"device": device})
        + "\n\nUSB identification may not establish the board model or bootloader.",
    )


def check_firmware_page(car_root, *, display=show_page):
    """Show the existing firmware check's summary and return to the submenu."""
    try:
        report = check_firmware(car_root)
        if report is not None:
            display("Check firmware", format_summary(report))
    except (OSError, RuntimeError, ValueError, TypeError, KeyError) as error:
        display("Firmware check failed", str(error))


def arduino_menu(car_root, *, select=select_item):
    """Host Arduino operations, with identification as the first menu entry."""
    actions = (
        ("Identify and select device", identify_device),
        ("Change firmware", change_firmware),
        ("Check firmware", check_firmware_page),
    )
    while True:
        selected = select("Arduino", [label for label, action in actions])
        if selected is None:
            return
        if not 0 <= selected < len(actions):
            raise ValueError("Invalid Arduino menu selection")
        actions[selected][1](car_root)
