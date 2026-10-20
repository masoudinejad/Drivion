"""Discover, inspect and persist a joystick through the shared terminal UI."""

from pathlib import Path

from ..ui.navigation import select_item, show_page


def _printable(value):
    return "".join(
        char if char.isprintable() or char == "\n" else " " for char in value
    )


def select_joystick(car_root, *, select=select_item, display=show_page, scan=None):
    """Select directly from discovered controllers; save without a detail page."""
    from car.src.config import load_config, update_config
    from car.src.joystick.discovery import discover, resolve_controller

    scan = discover if scan is None else scan
    controllers, errors = scan()
    if not controllers:
        details = "No accessible joysticks found. Connect a controller and check input-device permissions."
        if errors:
            details += "\n\nDevices that could not be inspected:\n" + "\n".join(errors)
        display("Connected joysticks", _printable(details))
        return
    saved = load_config(Path(car_root) / "config.toml").joystick
    title = (
        f"Select joystick (saved: {saved.name})"
        if saved.name
        else "Select joystick to save"
    )
    selected = select(
        _printable(title).replace("\n", " "),
        [
            _printable(f"{device.name} — {device.path}").replace("\n", " ")
            for device in controllers
        ],
    )
    if selected is None:
        return
    if not 0 <= selected < len(controllers):
        raise ValueError("Invalid joystick selection")
    device = controllers[selected]
    current, errors = scan()
    resolve_controller(current, device.identity)
    update_config(
        "joystick", device.identity.model_dump(), Path(car_root) / "config.toml"
    )


def joystick_menu(car_root, *, select=select_item):
    """Host joystick operations and return to management on Back."""
    actions = (("Identify and select device", select_joystick),)
    while True:
        selected = select("Joystick", [label for label, action in actions])
        if selected is None:
            return
        if not 0 <= selected < len(actions):
            raise ValueError("Invalid joystick menu selection")
        actions[selected][1](car_root)
