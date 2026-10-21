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
    from car.src.joystick.discovery import (
        discover,
        matches_identity,
        resolve_controller,
    )

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
    controls = saved.controls
    if not matches_identity(device.identity, saved):
        controls = controls.with_overrides(speed=None, steering=None)
    settings = device.identity.model_dump()
    settings["controls"] = controls.model_dump(exclude_none=True)
    update_config("joystick", settings, Path(car_root) / "config.toml")


def joystick_menu(car_root, *, select=select_item):
    """Host joystick operations and return to management on Back."""
    from .joystick_setup import configure_controls

    actions = (
        ("Identify and select device", select_joystick),
        ("Configure controls", configure_controls),
        ("Check controls", check_controls),
    )
    while True:
        selected = select("Joystick", [label for label, action in actions])
        if selected is None:
            return
        if not 0 <= selected < len(actions):
            raise ValueError("Invalid joystick menu selection")
        actions[selected][1](car_root)


def check_controls(car_root, *, factory=None, monitor_factory=None):
    """Monitor saved joystick settings until Escape; never write configuration."""
    from car.src.config import load_config
    from car.src.joystick import Joystick
    from car.system.ui.drive_monitor import DriveMonitor
    from car.system.ui.terminal import terminal_input

    settings = load_config(Path(car_root) / "config.toml").joystick
    factory = Joystick if factory is None else factory
    monitor_factory = DriveMonitor if monitor_factory is None else monitor_factory
    with (
        factory(settings) as joystick,
        terminal_input() as terminal,
    ):
        controls = settings.controls
        with monitor_factory(
            allow_reverse=controls.allow_reverse,
            speed_mode=controls.speed_mode,
            steering_mode=controls.steering_mode,
            stream=terminal.stream,
        ) as monitor:
            while True:
                current = joystick.read()
                monitor.update(
                    current.speed,
                    current.steering,
                    title="Joystick controls",
                    status="Saved control settings / Input demands",
                    footer=(
                        "Move sticks to check response / Esc Back",
                        "Wake an idle controller if sticks do not respond",
                    ),
                )
                if terminal.key(monitor.refresh_seconds) == "\x1b":
                    return
