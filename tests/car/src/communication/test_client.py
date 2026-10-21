"""Client lifecycle, reporting semantics and bounded command freshness."""

from dataclasses import dataclass

import pytest
from pydantic import ValidationError

from car.src.communication import Acknowledgement, Communication, Fields, Status
from car.src.communication import protocol as wire
from car.src.config import load_config
from car.system.arduino.settings import load_context


@dataclass
class Clock:
    now: float = 0

    def __call__(self):
        return self.now


class Peer:
    def __init__(self, clock):
        self.clock = clock
        self.decoder = wire.Decoder(1)
        self.input = bytearray()
        self.sent = []
        self.closed = False
        self.partial_write = False
        self.handshake_delay = 0.01

    def write(self, data):
        if self.partial_write:
            return 1
        for frame in self.decoder.feed(data, self.clock()):
            self.sent.append(frame)
            if frame.kind == wire.MessageType.HELLO:
                self.clock.now += self.handshake_delay
                self.reply(
                    wire.Frame(
                        wire.MessageType.WELCOME,
                        frame.session,
                        frame.sequence,
                        wire.WELCOME.pack(1000, 200, 60000, 3),
                    )
                )
        return len(data)

    def reply(self, frame):
        self.input += wire.encode(frame)

    def read(self, size):
        self.clock.now += 0.001
        chunk = bytes(self.input[:size])
        del self.input[:size]
        return chunk

    def close(self):
        self.closed = True


@pytest.fixture
def client():
    clock = Clock()
    peer = Peer(clock)
    comm = Communication(peer, load_config().communication, clock=clock)
    comm.connect()
    return comm, peer, clock


def test_target_units_sign_and_deadline(client):
    comm, peer, clock = client
    clock.now += 0.02
    sequence = comm.set_target(-250, 12.34)
    speed, angle, deadline = wire.TARGET.unpack(peer.sent[-1].payload)
    assert (speed, angle) == (-250, 1234)
    assert peer.sent[-1].sequence == sequence
    assert 1000 < deadline <= 1170


def test_snapshot_correlation_and_stream_order(client):
    comm, peer, _ = client
    sequence = comm.request_values()
    peer.reply(
        wire.Frame(
            wire.MessageType.TELEMETRY,
            comm.session,
            50,
            wire.TELEMETRY.pack(123, 400, -2500, 1),
        )
    )
    peer.reply(
        wire.Frame(
            wire.MessageType.SNAPSHOT,
            comm.session,
            sequence,
            wire.TELEMETRY.pack(120, -200, -2500, 3),
        )
    )
    values = comm.poll()
    assert values[0].speed_mm_s == 400
    assert values[0].steering_deg is None
    assert values[1].steering_deg == -25
    assert values[1].request_sequence == sequence
    peer.reply(
        wire.Frame(
            wire.MessageType.TELEMETRY,
            comm.session,
            49,
            wire.TELEMETRY.pack(123, 1, 1, 3),
        )
    )
    assert comm.poll() == []


def test_reporting_modes_and_status_staleness(client):
    comm, peer, clock = client
    comm.configure_reporting(0, Fields(0))
    comm.configure_reporting(100, Fields.SPEED | Fields.STEERING)
    assert comm.status_stale
    peer.reply(
        wire.Frame(
            wire.MessageType.STATUS, comm.session, 1, wire.STATUS.pack(1000, 1, 3, 10)
        )
    )
    assert len(comm.poll()) == 1
    assert not comm.status_stale
    clock.now += comm.config.status_stale_seconds
    assert comm.status_stale
    with pytest.raises(ValueError):
        comm.configure_reporting(1, Fields(4))


def test_old_session_and_invalid_reports_are_ignored(client):
    comm, peer, _ = client
    peer.reply(
        wire.Frame(
            wire.MessageType.TELEMETRY,
            comm.session ^ 1,
            0,
            wire.TELEMETRY.pack(0, 1, 2, 3),
        )
    )
    peer.reply(
        wire.Frame(
            wire.MessageType.TELEMETRY, comm.session, 0, wire.TELEMETRY.pack(0, 1, 2, 4)
        )
    )
    assert comm.poll() == []


def test_expired_clock_requires_explicit_renewal(client):
    comm, peer, clock = client
    old_session = comm.session
    clock.now += comm.config.max_session_age_seconds
    with pytest.raises(TimeoutError):
        comm.set_target(0, 0)
    comm.connect()
    assert comm.session != old_session
    comm.set_target(0, 0)
    assert peer.sent[-1].session == comm.session


def test_slow_handshake_is_rejected():
    clock = Clock()
    peer = Peer(clock)
    peer.handshake_delay = 0.2
    comm = Communication(peer, load_config().communication, clock=clock)
    with pytest.raises(TimeoutError, match="RTT"):
        comm.connect()
    assert comm.capabilities is None


def test_partial_write_invalidates_session(client):
    comm, peer, _ = client
    peer.partial_write = True
    with pytest.raises(OSError):
        comm.set_target(0, 0)
    with pytest.raises(RuntimeError):
        comm.stop()
    comm.close()
    assert peer.closed


@pytest.mark.parametrize(
    "speed,angle", [(2**31, 0), (True, 0), (0, float("nan")), (0, 400), (0, 1e308)]
)
def test_invalid_targets(client, speed, angle):
    with pytest.raises(ValueError):
        client[0].set_target(speed, angle)


@pytest.mark.parametrize(
    "changes",
    [
        {"read_budget_bytes": 0},
        {"pending_event_limit": 0},
        {"command_validity_ms": 50},
        {"frame_timeout_seconds": 0.001},
        {"baud_rate": True},
        {"unknown": 1},
    ],
)
def test_config_validation(changes):
    with pytest.raises(ValidationError):
        load_config().communication.with_overrides(**changes)


def test_firmware_and_runtime_share_baud():
    config = load_config()
    assert load_context().flash_settings["baud_rate"] == config.communication.baud_rate


def test_synchronize_preserves_session_and_reports(client):
    comm, peer, clock = client
    peer.reply(
        wire.Frame(
            wire.MessageType.TELEMETRY,
            comm.session,
            10,
            wire.TELEMETRY.pack(1000, 100, -1000, 3),
        )
    )
    comm.poll()
    values = comm.latest_values
    session = comm.session
    clock.now += comm.config.max_session_age_seconds
    comm.synchronize()
    assert comm.session == session
    assert comm.latest_values is values
    comm.set_target(0, 0)


def test_read_failure_invalidates_session(client):
    comm, peer, _ = client

    def fail_read(size):
        raise OSError("disconnected")

    peer.read = fail_read
    with pytest.raises(OSError, match="disconnected"):
        comm.poll()
    assert comm.capabilities is None


@pytest.mark.parametrize("read_budget", [24, 256])
def test_synchronize_preserves_pending_events_and_trailing_frames(client, read_budget):
    comm, peer, _ = client
    comm.config = comm.config.with_overrides(read_budget_bytes=read_budget)
    snapshot_request = comm.request_values()
    stop_request = comm.stop()
    peer.reply(
        wire.Frame(
            wire.MessageType.SNAPSHOT,
            comm.session,
            snapshot_request,
            wire.TELEMETRY.pack(1000, 100, -1000, 3),
        )
    )
    peer.reply(
        wire.Frame(
            wire.MessageType.ACK,
            comm.session,
            stop_request,
            wire.ACK.pack(wire.MessageType.STOP, wire.ErrorCode.OK),
        )
    )
    original_write = peer.write

    def write(data):
        result = original_write(data)
        peer.reply(
            wire.Frame(
                wire.MessageType.STATUS,
                comm.session,
                10,
                wire.STATUS.pack(1001, 0, 1, 1),
            )
        )
        return result

    peer.write = write
    comm.synchronize()
    events = comm.poll()
    while peer.input:
        events += comm.poll()
    assert len(events) == 3
    assert events[0].request_sequence == snapshot_request
    assert events[1] == Acknowledgement(
        stop_request, wire.MessageType.STOP, wire.ErrorCode.OK
    )
    assert isinstance(events[2], Status)
    assert comm.latest_values is events[0]
    assert comm.latest_status is events[2]
    assert comm.poll() == []


def test_synchronize_preserves_partial_frame(client):
    comm, peer, _ = client
    request = comm.request_values()
    packet = wire.encode(
        wire.Frame(
            wire.MessageType.SNAPSHOT,
            comm.session,
            request,
            wire.TELEMETRY.pack(1000, 100, 0, 3),
        )
    )
    peer.input += packet[:8]
    assert comm.poll() == []
    peer.input += packet[8:]
    comm.synchronize()
    assert comm.poll()[0].request_sequence == request


def test_synchronize_event_overflow_is_explicit_and_bounded(client):
    comm, peer, _ = client
    comm.config = comm.config.with_overrides(pending_event_limit=2)
    for sequence in range(3):
        peer.reply(
            wire.Frame(
                wire.MessageType.ACK,
                comm.session,
                sequence,
                wire.ACK.pack(wire.MessageType.STOP, wire.ErrorCode.OK),
            )
        )
    with pytest.raises(RuntimeError, match="pending event limit"):
        comm.synchronize()
    assert comm.capabilities is None
    assert len(comm._pending_events) <= 2
    comm.connect()
    assert comm.poll() == []


def test_repeated_synchronization_preserves_events_until_poll(client):
    comm, peer, _ = client
    for sequence in range(2):
        peer.reply(
            wire.Frame(
                wire.MessageType.ACK,
                comm.session,
                sequence,
                wire.ACK.pack(wire.MessageType.STOP, wire.ErrorCode.OK),
            )
        )
        comm.synchronize()
    assert [event.request_sequence for event in comm.poll()] == [0, 1]
