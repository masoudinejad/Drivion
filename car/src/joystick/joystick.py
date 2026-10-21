"""Absolute stick snapshots and normalized controls for a selected controller."""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from car.src.configuration.schema import (
    JoystickAxisConfig,
    JoystickConfig,
    JoystickControlsConfig,
)
from car.system.ui.progress import show_progress, show_success

from .calibration import AxisSample
from .discovery import device_identity, discover, matches_identity, resolve_controller


@dataclass(frozen=True)
class ControlInput:
    """Unitless demands in [-1, 1]; forward and right are positive."""

    speed: float
    steering: float


def interpret_axis(
    raw: int,
    calibration: JoystickAxisConfig,
    dead_zone: float,
    mode: Literal["fixed", "accurate"],
) -> float:
    """Normalize each side independently, remove dead zone, then apply mode."""
    delta = raw - calibration.centre
    travel = (
        calibration.maximum - calibration.centre
        if delta >= 0
        else calibration.centre - calibration.minimum
    )
    value = max(-1.0, min(1.0, delta / travel))
    if calibration.inverted:
        value = -value
    if abs(value) <= dead_zone:
        return 0.0
    sign = 1.0 if value > 0 else -1.0
    if mode == "fixed":
        return sign
    return sign * (abs(value) - dead_zone) / (1 - dead_zone)


class Joystick:
    """Open from config, read current stick positions, and own the device lifetime.

    ``read()`` queries current kernel axis state directly, so idle sticks remain
    valid without new events and queued events cannot replay obsolete commands.
    No threads, input grabbing, drive commands, or automatic reconnection are used.
    Calls must be serialized. ``for_setup`` permits opening before calibration.
    """

    def __init__(
        self, config: JoystickConfig, *, for_setup=False, backend=None, scan=None
    ):
        self.config = config
        self._device = None
        self._axes = {}
        with show_progress("Initializing joystick"):
            if not for_setup and (
                config.controls.speed is None or config.controls.steering is None
            ):
                raise ValueError(
                    "Configure joystick controls in system management first."
                )
            if backend is None:
                try:
                    import evdev as backend
                except ImportError as error:
                    raise RuntimeError(
                        "Joystick input requires evdev on Linux."
                    ) from error
            devices, errors = discover(backend=backend) if scan is None else scan()
            try:
                observed = resolve_controller(devices, config)
            except RuntimeError as error:
                detail = "; ".join(errors)
                raise RuntimeError(
                    str(error) + (f" {detail}" if detail else "")
                ) from error
            try:
                self._device = backend.InputDevice(observed.path, readonly=True)
                opened_identity = device_identity(self._device)
                if not matches_identity(opened_identity, config):
                    raise RuntimeError(
                        "Joystick changed while opening. Identify it again."
                    )
                capabilities = self._device.capabilities(absinfo=True)
                self._axes = {
                    str(backend.ecodes.ABS.get(code, code)): code
                    for code, _ in capabilities.get(backend.ecodes.EV_ABS, [])
                }
                if not for_setup:
                    self._control_snapshot(config.controls)
            except BaseException:
                self.close()
                raise
        name = "".join(char if char.isprintable() else " " for char in config.name)
        show_success(f"Joystick initialized: {name}")

    def axis_snapshot(
        self, names: Iterable[str] | None = None
    ) -> dict[str, AxisSample]:
        """Return current axis metadata; unknown names raise ValueError.

        I/O failures invalidate the device. Invalid requests leave it open.
        """
        if self._device is None:
            raise RuntimeError("Joystick is closed or disconnected.")
        names = tuple(self._axes) if names is None else tuple(names)
        for name in names:
            if name not in self._axes:
                raise ValueError(f"Joystick axis {name} is unavailable.")
        try:
            snapshot = {name: self._device.absinfo(self._axes[name]) for name in names}
            if any(axis is None for axis in snapshot.values()):
                raise OSError("Joystick axis state is unavailable.")
            return snapshot
        except OSError:
            self.close()
            raise

    def _control_snapshot(
        self, controls: JoystickControlsConfig
    ) -> dict[str, AxisSample]:
        """Validate saved and pending mappings against the same sampled metadata."""
        if controls.speed is None or controls.steering is None:
            raise ValueError("Joystick controls have not been calibrated.")
        calibrations = (controls.speed, controls.steering)
        axes = self.axis_snapshot(calibration.axis for calibration in calibrations)
        for calibration in calibrations:
            axis = axes[calibration.axis]
            if (
                not axis.min
                <= calibration.minimum
                < calibration.centre
                < calibration.maximum
                <= axis.max
            ):
                raise ValueError(
                    "Joystick axis range changed. Configure controls again."
                )
        return axes

    def read(self, *, controls: JoystickControlsConfig | None = None) -> ControlInput:
        """Return current normalized speed and steering, or raise on device failure.

        An optional controls section previews pending settings without modifying config.
        Axes are sampled in sequence rather than as an atomic input-event frame.
        A read error returns no demand; the caller must stop applying prior input.
        """
        controls = self.config.controls if controls is None else controls
        axes = self._control_snapshot(controls)
        speed = interpret_axis(
            axes[controls.speed.axis].value,
            controls.speed,
            controls.dead_zone,
            controls.speed_mode,
        )
        steering = interpret_axis(
            axes[controls.steering.axis].value,
            controls.steering,
            controls.dead_zone,
            controls.steering_mode,
        )
        if not controls.allow_reverse:
            speed = max(0.0, speed)
        return ControlInput(speed, steering)

    def close(self):
        """Release the device; repeated calls are harmless."""
        device, self._device = self._device, None
        if device is not None:
            device.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
