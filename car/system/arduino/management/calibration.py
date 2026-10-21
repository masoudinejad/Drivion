"""Guided physical servo calibration, with one acknowledged command at a time."""

import math
import struct
import subprocess
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path

from car.src.communication import Acknowledgement, Communication
from car.src.communication import protocol as wire
from car.src.configuration.firmware import validate_steering

from ...ui.navigation import confirm, show_page
from ...ui.terminal import terminal_input


@dataclass(frozen=True)
class CalibrationSettings:
    fine_step_us: int
    coarse_step_us: int
    poll_interval_seconds: float
    heartbeat_interval_seconds: float
    ack_timeout_seconds: float
    sync_interval_seconds: float

    @classmethod
    def load(cls, root, parameters, communication):
        with (root / "system/pyproject.toml").open("rb") as stream:
            settings = cls(
                **tomllib.load(stream)["tool"]["drivion"]["steering_calibration"]
            )
        if not (
            type(settings.fine_step_us) is int
            and type(settings.coarse_step_us) is int
            and 0
            < settings.fine_step_us
            <= settings.coarse_step_us
            <= parameters["CALIBRATION_STEP_US"]
        ):
            raise ValueError("Calibration steps must fit the firmware's nudge limit")
        for field in (
            "poll_interval_seconds",
            "heartbeat_interval_seconds",
            "ack_timeout_seconds",
            "sync_interval_seconds",
        ):
            value = getattr(settings, field)
            if (
                type(value) not in (int, float)
                or not math.isfinite(value)
                or not 0 < value <= 60
            ):
                raise ValueError(f"Invalid calibration setting: {field}")
        lease = (
            min(parameters["STEERING_TIMEOUT_MS"], communication.command_validity_ms)
            / 1000
        )
        if (
            settings.poll_interval_seconds + settings.heartbeat_interval_seconds
            >= lease
        ):
            raise ValueError("Calibration heartbeat must fit inside the command lease")
        uncertainty = (
            communication.max_handshake_rtt_seconds
            + settings.sync_interval_seconds * communication.clock_drift_ppm / 1e6
        )
        if (
            settings.sync_interval_seconds >= communication.max_session_age_seconds
            or uncertainty >= lease
        ):
            raise ValueError(
                "Calibration clock synchronization must fit the command lease"
            )
        return settings


def initial_pulse(parameters):
    return math.floor(
        parameters["SERVO_MIN_US"]
        + parameters["SERVO_CENTER_DEG"]
        * (parameters["SERVO_MAX_US"] - parameters["SERVO_MIN_US"])
        / 180
        + 0.5
    )


def calibration_signature(parameters):
    """Check the running pin, pulse range, start, nudge bound, and watchdog."""
    return wire.checksum(
        struct.pack(
            "<HHHHHI",
            parameters["SERVO_PIN"],
            parameters["SERVO_MIN_US"],
            parameters["SERVO_MAX_US"],
            initial_pulse(parameters),
            parameters["CALIBRATION_STEP_US"],
            parameters["STEERING_TIMEOUT_MS"],
        )
    )


class CalibrationLink:
    """Serialize acknowledged moves; a failed lease or ACK aborts without retry."""

    def __init__(self, client, parameters, settings, *, clock=time.monotonic):
        self.client, self.parameters, self.settings, self.clock = (
            client,
            parameters,
            settings,
            clock,
        )
        self.signature = calibration_signature(parameters)
        self.pulse = initial_pulse(parameters)
        self.last_send = self.last_sync = clock()
        self.started = False

    def command(self, action, pulse=None):
        pulse = self.pulse if pulse is None else pulse
        sequence = self.client.calibrate_steering(action, pulse, self.signature)
        started = self.clock()
        self.last_send = started
        while self.clock() - started < self.settings.ack_timeout_seconds:
            for event in self.client.poll():
                if (
                    isinstance(event, Acknowledgement)
                    and event.request_sequence == sequence
                    and event.message_type == wire.MessageType.CALIBRATE_STEERING
                ):
                    if event.error != wire.ErrorCode.OK:
                        raise RuntimeError(
                            f"Calibration rejected ({event.error.name}). Flash the current steering firmware with these settings before starting; restart the board after an expired calibration."
                        )
                    self.pulse = pulse
                    return
        raise TimeoutError("Calibration acknowledgement missing; session stopped")

    def begin(self):
        # STOP cannot actuate the drive motor in the steering-only firmware.
        self.client.stop()
        self.started = True  # Also attempt END if the BEGIN acknowledgement is lost.
        self.command(wire.CalibrationAction.BEGIN)
        self.command(wire.CalibrationAction.MOVE)

    def service(self):
        now = self.clock()
        if now - self.last_sync >= self.settings.sync_interval_seconds:
            self.command(wire.CalibrationAction.KEEP_ALIVE)
            self.client.synchronize()
            self.last_sync = self.clock()
        if self.clock() - self.last_send >= self.settings.heartbeat_interval_seconds:
            self.command(wire.CalibrationAction.KEEP_ALIVE)

    def move(self, pulse):
        self.command(wire.CalibrationAction.MOVE, pulse)

    def finish(self, disable=False):
        if self.started:
            self.command(
                wire.CalibrationAction.DISABLE
                if disable
                else wire.CalibrationAction.END
            )


class CalibrationWizard:
    """Observation-driven state, independent of terminal and serial hardware."""

    def __init__(self, parameters, settings):
        self.parameters, self.settings = dict(parameters), settings
        self.pulse = self.goal = initial_pulse(parameters)
        self.phase = "straight"
        self.center = self.left = self.right = None
        self.increasing_is_right = None
        self.message = ""
        self.done = self.cancelled = self.disable = False

    def key(self, key):
        self.message = ""
        if key in ("\x1b", "q"):
            self.cancelled = True
            return
        if key in ("x", "n", "c"):
            self.cancelled = self.disable = True
            self.message = {
                "x": "Servo signal disabled.",
                "n": "No movement: check servo power, shared ground, signal pin, and flashed firmware. Settings were not saved.",
                "c": "Continuous rotation: this steering setup requires a positional servo, or a position-feedback controller. Signal disabled; settings were not saved.",
            }[key]
            return
        if self.pulse != self.goal:
            self.message = "Moving in bounded steps; wait or press X to disable."
            return
        if self.phase == "verify":
            if key in ("l", "s", "r"):
                self.goal = {"l": self.left, "s": self.center, "r": self.right}[key]
                self.tested.add(key)
            elif key in ("\r", "\n"):
                if self.tested == {"l", "s", "r"} and self.pulse == self.center:
                    self.done = True
                else:
                    self.message = (
                        "Test L, R and S; finish with wheels straight before saving."
                    )
            return
        if key in ("a", "d", "A", "D"):
            direction = -1 if key.lower() == "a" else 1
            if self.phase in ("left", "right") and not self.increasing_is_right:
                direction *= -1
            step = (
                self.settings.fine_step_us
                if key.islower()
                else self.settings.coarse_step_us
            )
            self.goal = max(
                self.parameters["SERVO_MIN_US"],
                min(self.parameters["SERVO_MAX_US"], self.pulse + direction * step),
            )
        elif self.phase == "direction" and key in ("l", "r"):
            if self.pulse == self.center:
                self.message = "Nudge first, then report which way the wheels turned."
                return
            self.increasing_is_right = (self.pulse > self.center) == (key == "r")
            self.phase, self.goal = "left", self.center
        elif key in ("\r", "\n"):
            if self.phase == "straight":
                self.center, self.phase = self.pulse, "direction"
            elif self.phase == "left":
                if not self.correct_side(left=True):
                    self.message = (
                        "Move the wheels left of straight before marking left."
                    )
                    return
                self.left, self.phase, self.goal = self.pulse, "right", self.center
            elif self.phase == "right":
                if not self.correct_side(left=False):
                    self.message = (
                        "Move the wheels right of straight before marking right."
                    )
                    return
                self.right, self.phase, self.goal = self.pulse, "verify", self.center
                self.tested = set()

    def correct_side(self, *, left):
        return self.pulse != self.center and (
            (self.pulse < self.center)
            == (self.increasing_is_right if left else not self.increasing_is_right)
        )

    def next_pulse(self):
        step = self.settings.coarse_step_us
        return self.pulse + max(-step, min(step, self.goal - self.pulse))

    def values(self):
        if not self.done:
            raise ValueError("Calibration has not been verified")
        values = dict(self.parameters)
        for key, pulse in (
            ("SERVO_LEFT_DEG", self.left),
            ("SERVO_CENTER_DEG", self.center),
            ("SERVO_RIGHT_DEG", self.right),
        ):
            values[key] = (
                (pulse - values["SERVO_MIN_US"])
                * 180
                / (values["SERVO_MAX_US"] - values["SERVO_MIN_US"])
            )
        validate_steering(values)
        return values

    def render(self):
        instructions = {
            "straight": "1. Find straight: A/D lower/higher pulse; Shift+A/D coarse. Enter = wheels point straight.",
            "direction": "2. Nudge with A/D, observe from behind the car: L = turned left, R = turned right.",
            "left": "3. Set usable LEFT limit: A moves left, D moves right (Shift = coarse). Enter marks it. Stop before binding.",
            "right": "4. Set usable RIGHT limit: A moves left, D moves right (Shift = coarse). Enter marks it. Stop before binding.",
            "verify": "5. Verify: L = left, R = right, S = straight. Check all three, finish at S, then Enter.",
        }
        return (
            f"Guided servo calibration — {self.phase}\n\n{instructions[self.phase]}\n\n"
            f"Pulse: {self.pulse} µs   Target: {self.goal} µs\n"
            f"Straight: {self.center}   Left: {self.left}   Right: {self.right}\n\n"
            "X = disable signal immediately   N = no movement   C = keeps rotating\n"
            "Q / Escape = cancel   Ctrl+C = cancel\n\n" + self.message
        )


def apply_steering_firmware(root, *, display=show_page):
    """Apply saved calibration using the existing reviewed compile/flash steps."""
    from ..device.flash import flash_firmware
    from ..firmware.compile import compile_firmware

    artifacts = compile_firmware("steering", root)
    if artifacts is None:
        display(
            "Calibration saved; application pending",
            "Compilation cancelled. Compile and flash steering before driving with the new calibration.",
        )
        return
    log = flash_firmware(artifacts, root)
    if log is None:
        display(
            "Calibration saved; application pending",
            "Flashing cancelled. Use Arduino -> Change firmware -> steering before driving with the new calibration.",
        )
    else:
        display(
            "Steering calibration applied",
            "Running firmware verified. Restart the Pi driving application before driving.",
        )


def guided_calibration(
    car_root,
    *,
    approve=confirm,
    display=show_page,
    factory=None,
    terminal=terminal_input,
    apply=apply_steering_firmware,
):
    """Capture, verify, save atomically, and offer to apply a physical calibration."""
    from car.src.config import load_config, update_config
    from ..firmware.definitions import load_firmware

    root = Path(car_root)
    wizard = None
    cleanup_error = None
    try:
        config = load_config(root / "config.toml")
        parameters = config.firmware["steering"]
        load_firmware("steering", root, parameters)
        settings = CalibrationSettings.load(root, parameters, config.communication)
        if not approve(
            "Start live servo calibration? Stop driving, disconnect drive-motor power, lift the wheels, and close other serial users. The current steering firmware must be flashed with the configured pin and pulse range. Keep clear of moving parts."
        ):
            return
        factory = Communication.open if factory is None else factory
        wizard = CalibrationWizard(parameters, settings)
        with factory(config.arduino.address, config.communication) as client:
            link = CalibrationLink(client, parameters, settings)
            try:
                with terminal() as keyboard:
                    link.begin()
                    last_view = None
                    while not (wizard.done or wizard.cancelled):
                        link.service()
                        view = wizard.render()
                        if view != last_view:
                            keyboard.stream.write("\033[H\033[2J" + view)
                            keyboard.stream.flush()
                            last_view = view
                        key = keyboard.key(settings.poll_interval_seconds)
                        if key is not None:
                            previous_center = wizard.center
                            wizard.key(key if key in ("A", "D") else key.lower())
                            if wizard.center is not None and previous_center is None:
                                link.command(wire.CalibrationAction.MARK_CENTER)
                        if not wizard.cancelled and wizard.pulse != wizard.goal:
                            pulse = wizard.next_pulse()
                            link.move(pulse)
                            wizard.pulse = pulse
            finally:
                try:
                    link.finish(disable=wizard.disable)
                except (OSError, RuntimeError, ValueError, TimeoutError) as error:
                    cleanup_error = str(error)
        if cleanup_error:
            raise RuntimeError(
                "Could not confirm calibration shutdown; firmware lease will expire. "
                + cleanup_error
            )
        if wizard.cancelled:
            display(
                "Calibration stopped",
                (
                    wizard.message
                    or "No settings saved. Returned to confirmed straight, or disabled the signal if straight was unknown."
                )
                + " Restart or reflash the board before driving.",
            )
            return
        values = wizard.values()
        direction = (
            "increasing pulse turns right"
            if wizard.increasing_is_right
            else "increasing pulse turns left (inverted)"
        )
        summary = f"Direction: {direction}\n" + "\n".join(
            f"{key} = {values[key]:.3f}°"
            for key in ("SERVO_LEFT_DEG", "SERVO_CENTER_DEG", "SERVO_RIGHT_DEG")
        )
        display(
            "Calibration preview",
            summary
            + "\n\nPhysical steering-angle limits remain unchanged; set those separately if measured. Firmware must be reflashed to persist these servo positions.",
        )
        if not approve("Save this verified calibration to config.toml?"):
            display(
                "Calibration discarded",
                "No settings saved. Restart or reflash the board before driving.",
            )
            return
        update_config("firmware.steering", values, root / "config.toml")
        if approve("Compile and flash the saved steering calibration now?"):
            apply(root)
        else:
            display(
                "Calibration saved; application pending",
                "Use Arduino -> Change firmware -> steering before driving. Calibration disables normal driving until the board is restarted or flashed; restart alone still uses the old calibration.",
            )
    except (
        OSError,
        RuntimeError,
        ValueError,
        TypeError,
        KeyError,
        subprocess.SubprocessError,
    ) as error:
        display(
            "Guided calibration failed",
            str(error)
            + " If calibration started, restart or reflash the board before driving.",
        )
