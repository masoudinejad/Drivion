"""Single-owner, explicitly polled communication client without actuator policy."""

import math
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass

from car.src.configuration.schema import CommunicationConfig

from . import protocol as wire
from .transport import ByteTransport, open_serial


@dataclass(frozen=True)
class Capabilities:
    command_timeout_ms: int
    max_telemetry_interval_ms: int
    fields: wire.Fields


@dataclass(frozen=True)
class ReportedValues:
    """Application-provided values, never presumed to be physical measurements."""

    sample_time_ms: int
    speed_mm_s: int | None
    steering_deg: float | None
    received_at: float
    sequence: int
    request_sequence: int | None


@dataclass(frozen=True)
class Status:
    board_time_ms: int
    command_active: bool
    last_command_sequence: int
    command_age_ms: int
    received_at: float


@dataclass(frozen=True)
class Acknowledgement:
    request_sequence: int
    message_type: int
    error: wire.ErrorCode


class Communication:
    """Transport targets and reports. Calls must be serialized by the application.

    No implicit drive retries, background threads, rearming, or actuator control.
    Call poll frequently; set_target sends a new application-supplied target.
    connect establishes or renews a session and invalidates its previous commands.
    """

    def __init__(
        self,
        transport: ByteTransport,
        config: CommunicationConfig,
        *,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.transport = transport
        self.config = config
        self.clock = clock
        self.decoder = wire.Decoder(config.frame_timeout_seconds)
        self.session = 0
        self.sequence = 0
        self.capabilities: Capabilities | None = None
        self.latest_values: ReportedValues | None = None
        self.latest_status: Status | None = None
        self._board_time = 0
        self._connected_at = 0.0
        self._rtt = 0.0
        self._last_board_sequence: int | None = None
        self._last_telemetry_sequence: int | None = None
        self.closed = False

    @classmethod
    def open(cls, address: str, config: CommunicationConfig):
        """Open USB serial, accommodate reset, and negotiate before returning."""
        client = cls(open_serial(address, config), config)
        try:
            time.sleep(config.boot_wait_seconds)
            client.connect()
            return client
        except BaseException:
            client.close()
            raise

    def connect(self):
        """Negotiate a fresh session, invalidating previously accepted commands."""
        return self._handshake(new_session=True)

    def synchronize(self):
        """Refresh the board clock without resetting the session or targets.

        Schedule before the clock estimate expires. This bounded exchange pauses
        sending; the application's Arduino timeout policy remains in force.
        """
        self._require_session()
        return self._handshake(new_session=False)

    def _handshake(self, *, new_session):
        if self.closed:
            raise RuntimeError("communication is closed")
        self.capabilities = None
        if new_session:
            self.latest_values = self.latest_status = None
            self._last_board_sequence = self._last_telemetry_sequence = None
            self.session = secrets.randbelow(0xFFFFFFFF) + 1
            self.sequence = 0
        self.decoder = wire.Decoder(self.config.frame_timeout_seconds)
        started = self.clock()
        request = self._send(wire.MessageType.HELLO)
        while self.clock() - started < self.config.handshake_timeout_seconds:
            frames = self.decoder.feed(
                self.transport.read(self.config.read_budget_bytes), self.clock()
            )
            for frame in frames:
                if (
                    frame.session != self.session
                    or frame.kind != wire.MessageType.WELCOME
                    or frame.sequence != request
                    or len(frame.payload) != wire.WELCOME.size
                ):
                    continue
                board_time, watchdog, max_interval, fields = wire.WELCOME.unpack(
                    frame.payload
                )
                received = self.clock()
                rtt = received - started
                if rtt > self.config.max_handshake_rtt_seconds:
                    raise TimeoutError(
                        "handshake RTT exceeds configured uncertainty budget"
                    )
                if (
                    not 0 < watchdog < 0x80000000
                    or not 0 < max_interval < 0x80000000
                    or fields & ~int(wire.Fields.SPEED | wire.Fields.STEERING)
                ):
                    raise ValueError("invalid peer capabilities")
                if self.config.command_validity_ms > watchdog:
                    raise ValueError("command validity exceeds Arduino watchdog")
                self._board_time, self._connected_at, self._rtt = (
                    board_time,
                    received,
                    rtt,
                )
                self.capabilities = Capabilities(
                    watchdog, max_interval, wire.Fields(fields)
                )
                return self.capabilities
        raise TimeoutError("Arduino did not negotiate communication before deadline")

    @property
    def status_stale(self) -> bool:
        return (
            self.latest_status is None
            or self.clock() - self.latest_status.received_at
            >= self.config.status_stale_seconds
        )

    def set_target(self, speed_mm_s: int, steering_deg: float) -> int:
        """Send signed mm/s and degrees (center zero, right positive).

        Angle is quantized to 0.01 degree. Deadline uses a conservative lower
        bound on the board clock, preventing delayed targets acquiring a new lease.
        """
        self._require_session()
        if type(speed_mm_s) is not int or not -(2**31) <= speed_mm_s < 2**31:
            raise ValueError("speed_mm_s must be a signed int32")
        if type(steering_deg) not in (int, float) or not math.isfinite(steering_deg):
            raise ValueError("steering_deg must be finite")
        if not -327.68 <= steering_deg <= 327.67:
            raise ValueError("steering angle exceeds wire range")
        angle = round(steering_deg * 100)
        elapsed = self.clock() - self._connected_at
        uncertainty_ms = self._rtt * 1000 + elapsed * self.config.clock_drift_ppm / 1000
        if (
            elapsed >= self.config.max_session_age_seconds
            or uncertainty_ms >= self.config.command_validity_ms
        ):
            raise TimeoutError(
                "session clock estimate expired; call synchronize to refresh"
            )
        deadline = (
            self._board_time
            + math.floor(elapsed * 1000 - uncertainty_ms)
            + self.config.command_validity_ms
        ) & 0xFFFFFFFF
        return self._send(
            wire.MessageType.DRIVE_TARGET, wire.TARGET.pack(speed_mm_s, angle, deadline)
        )

    def stop(self) -> int:
        """Request a stop event; the Arduino application chooses actuator behavior."""
        self._require_session()
        return self._send(wire.MessageType.STOP)

    def request_values(self) -> int:
        """Request all available values; the snapshot echoes the returned sequence."""
        self._require_session()
        return self._send(wire.MessageType.GET_TELEMETRY)

    def configure_reporting(self, interval_ms: int, fields: wire.Fields) -> int:
        """Zero interval disables streaming. Nonzero interval enables streaming."""
        self._require_session()
        if (
            type(interval_ms) is not int
            or not 0 <= interval_ms <= self.capabilities.max_telemetry_interval_ms
        ):
            raise ValueError("reporting interval exceeds peer capability")
        if (
            not isinstance(fields, wire.Fields)
            or int(fields) & ~int(self.capabilities.fields)
            or (interval_ms and not fields)
        ):
            raise ValueError("unsupported or empty reporting fields")
        return self._send(
            wire.MessageType.SET_TELEMETRY,
            wire.TELEMETRY_CONFIG.pack(interval_ms, int(fields)),
        )

    def poll(self) -> list[ReportedValues | Status | Acknowledgement]:
        """Read at most the configured byte budget and return validated events.

        Callers correlate acknowledgements with returned request sequences.
        Keep polling even with reporting disabled to receive essential status.
        """
        self._require_session()
        try:
            data = self.transport.read(self.config.read_budget_bytes)
        except BaseException:
            self.capabilities = None
            raise
        now = self.clock()
        frames = self.decoder.feed(data, now)
        events = []
        for frame in frames:
            if frame.session != self.session:
                continue
            if (
                frame.kind == wire.MessageType.ACK
                and len(frame.payload) == wire.ACK.size
            ):
                kind, code = wire.ACK.unpack(frame.payload)
                try:
                    events.append(
                        Acknowledgement(frame.sequence, kind, wire.ErrorCode(code))
                    )
                except ValueError:
                    pass
            elif (
                frame.kind in (wire.MessageType.TELEMETRY, wire.MessageType.SNAPSHOT)
                and len(frame.payload) == wire.TELEMETRY.size
            ):
                if (
                    frame.kind == wire.MessageType.TELEMETRY
                    and self._last_telemetry_sequence is not None
                    and not wire.newer(frame.sequence, self._last_telemetry_sequence)
                ):
                    continue
                timestamp, speed, angle, valid = wire.TELEMETRY.unpack(frame.payload)
                if valid & ~int(self.capabilities.fields):
                    continue
                if frame.kind == wire.MessageType.TELEMETRY:
                    self._last_telemetry_sequence = frame.sequence
                self.latest_values = ReportedValues(
                    timestamp,
                    speed if valid & wire.Fields.SPEED else None,
                    angle / 100 if valid & wire.Fields.STEERING else None,
                    now,
                    frame.sequence,
                    frame.sequence if frame.kind == wire.MessageType.SNAPSHOT else None,
                )
                events.append(self.latest_values)
            elif (
                frame.kind == wire.MessageType.STATUS
                and len(frame.payload) == wire.STATUS.size
            ):
                if self._last_board_sequence is not None and not wire.newer(
                    frame.sequence, self._last_board_sequence
                ):
                    continue
                timestamp, active, last, age = wire.STATUS.unpack(frame.payload)
                if active not in (0, 1):
                    continue
                self._last_board_sequence = frame.sequence
                self.latest_status = Status(timestamp, bool(active), last, age, now)
                events.append(self.latest_status)
        return events

    def _require_session(self):
        if self.closed or self.capabilities is None:
            raise RuntimeError("communication session is not connected")

    def _send(self, kind, payload=b""):
        sequence = self.sequence
        self.sequence = (sequence + 1) & 0xFFFF
        packet = wire.encode(wire.Frame(kind, self.session, sequence, payload))
        try:
            if self.transport.write(packet) != len(packet):
                raise OSError("serial frame was only partially written")
        except BaseException:
            self.capabilities = None
            raise
        return sequence

    def close(self):
        """Release transport; Arduino reports a timeout if a target remains active."""
        if not self.closed:
            self.closed = True
            self.capabilities = None
            self.transport.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
