"""Read Linux controller identities and capabilities without consuming input."""

from dataclasses import dataclass
from pathlib import Path

from car.src.configuration.schema import JoystickIdentity


@dataclass(frozen=True)
class Controller:
    """An observed controller; the event path is only valid for this scan."""

    identity: JoystickIdentity
    path: str
    specifications: str

    @property
    def name(self):
        return self.identity.name


def device_identity(device) -> JoystickIdentity:
    """Read the same identity fields during discovery and the opening recheck."""
    return JoystickIdentity(
        name=device.name,
        vendor=device.info.vendor,
        product=device.info.product,
        unique_id=device.uniq or "",
    )


def discover(*, backend=None, input_directory=Path("/dev/input")):
    """Return controllers and per-device errors, closing every opened device.

    Use gamepad/joystick buttons plus absolute axes to exclude keyboards and
    mice. Enumerate paths ourselves: evdev.list_devices hides inaccessible nodes.
    Identity uses the hardware unique ID when available, otherwise model metadata;
    identical controllers without unique IDs remain ambiguous. Paths are diagnostic.
    """
    if backend is None:
        try:
            import evdev as backend
        except ImportError as error:
            raise RuntimeError("Joystick discovery requires evdev on Linux.") from error
    controllers, errors = [], []
    codes = backend.ecodes
    for path in sorted(Path(input_directory).glob("event*")):
        device = None
        try:
            device = backend.InputDevice(str(path), readonly=True)
            capabilities = device.capabilities(absinfo=True)
            buttons = capabilities.get(codes.EV_KEY, [])
            axes = capabilities.get(codes.EV_ABS, [])
            if not axes or not any(
                codes.BTN_JOYSTICK <= button < codes.BTN_DIGI
                or codes.BTN_TRIGGER_HAPPY <= button <= codes.BTN_TRIGGER_HAPPY40
                for button in buttons
            ):
                continue
            info = device.info
            identity = device_identity(device)
            lines = [
                f"Name: {device.name}",
                f"Device: {path}",
                (
                    f"Bus: {info.bustype:04x}; vendor: {info.vendor:04x}; "
                    f"product: {info.product:04x}; version: {info.version:04x}"
                ),
                f"Unique ID: {device.uniq or '(unavailable)'}",
                f"Physical connection: {device.phys or '(unavailable)'}",
                f"Buttons ({len(buttons)}): "
                + ", ".join(
                    str(codes.bytype[codes.EV_KEY].get(button, button))
                    for button in buttons
                ),
                f"Axes ({len(axes)}):",
            ]
            for code, axis in axes:
                lines.append(
                    f"  {codes.ABS.get(code, code)}: min={axis.min}, max={axis.max}, "
                    f"flat={axis.flat}, fuzz={axis.fuzz}, resolution={axis.resolution}"
                )
            controllers.append(Controller(identity, str(path), "\n".join(lines)))
        except OSError as error:
            errors.append(f"{path}: {error}")
        finally:
            if device is not None:
                device.close()
    return controllers, errors


def matches_identity(observed, saved):
    """Match hardware metadata and optional unique ID, independently of paths."""
    if not saved.name:
        return False
    fields = ("name", "vendor", "product")
    if any(getattr(observed, field) != getattr(saved, field) for field in fields):
        return False
    if saved.unique_id:
        return observed.unique_id == saved.unique_id
    return True


def resolve_controller(controllers, identity):
    """Require exactly one current device with the saved identity."""
    matches = [
        device for device in controllers if matches_identity(device.identity, identity)
    ]
    if len(matches) != 1:
        raise RuntimeError(
            "Selected joystick disconnected, changed, or is ambiguous. Scan again."
        )
    return matches[0]
