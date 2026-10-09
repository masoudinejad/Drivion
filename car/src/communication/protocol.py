"""Version 1 bounded serial frames; constants are protocol, not runtime settings."""

import struct
from dataclasses import dataclass
from enum import IntEnum, IntFlag

VERSION = 1
FLAG = 0x7E
ESCAPE = 0x7D
MAX_FRAME_BYTES = 96
HEADER = struct.Struct("<BBIHH")
CRC = struct.Struct("<H")
TARGET = struct.Struct("<ihI")
WELCOME = struct.Struct("<IIIH")
TELEMETRY_CONFIG = struct.Struct("<IH")
TELEMETRY = struct.Struct("<IihH")
STATUS = struct.Struct("<IBHI")
ACK = struct.Struct("<BB")


class MessageType(IntEnum):
    HELLO = 1
    WELCOME = 2
    DRIVE_TARGET = 3
    STOP = 4
    SET_TELEMETRY = 5
    GET_TELEMETRY = 6
    TELEMETRY = 7
    STATUS = 8
    ACK = 9
    SNAPSHOT = 10


class Fields(IntFlag):
    SPEED = 1
    STEERING = 2


class ErrorCode(IntEnum):
    OK = 0
    BAD_PAYLOAD = 1
    UNSUPPORTED = 2
    STALE = 3
    EXPIRED = 4
    BUSY = 5


@dataclass(frozen=True)
class Frame:
    """Validated envelope. Unknown message types remain available for extensions."""

    kind: int
    session: int
    sequence: int
    payload: bytes = b""


def checksum(data: bytes) -> int:
    """RFC 1662 FCS-16, reflected polynomial 0x8408, complemented result."""
    value = 0xFFFF
    for byte in data:
        value ^= byte
        for _ in range(8):
            value = (value >> 1) ^ (0x8408 if value & 1 else 0)
    return value ^ 0xFFFF


def encode(frame: Frame) -> bytes:
    body = (
        HEADER.pack(
            VERSION, frame.kind, frame.session, frame.sequence, len(frame.payload)
        )
        + frame.payload
    )
    if len(body) + CRC.size > MAX_FRAME_BYTES:
        raise ValueError("frame exceeds protocol size limit")
    body += CRC.pack(checksum(body))
    output = bytearray([FLAG])
    for byte in body:
        if byte in (FLAG, ESCAPE):
            output.extend((ESCAPE, byte ^ 0x20))
        else:
            output.append(byte)
    output.append(FLAG)
    return bytes(output)


def newer(sequence: int, previous: int) -> bool:
    """Compare uint16 sequences with a half-range window, including wraparound."""
    return 0 < ((sequence - previous) & 0xFFFF) < 0x8000


class Decoder:
    """Incremental bounded decoder; corruption is discarded at delimiters."""

    def __init__(self, frame_timeout_seconds: float):
        self.timeout = frame_timeout_seconds
        self.buffer = bytearray()
        self.active = False
        self.escaped = False
        self.discard = False
        self.started = 0.0
        self.rejected_frames = 0

    def feed(self, data: bytes, now: float) -> list[Frame]:
        if self.active and now - self.started >= self.timeout:
            if self.buffer or self.escaped or self.discard:
                self.rejected_frames += 1
            self._reset(now)
            self.active = False
        frames = []
        for byte in data:
            if byte == FLAG:
                if self.active and (self.buffer or self.discard or self.escaped):
                    frame = self._finish()
                    if frame is not None:
                        frames.append(frame)
                self._reset(now)
                self.active = True
            elif self.active and not self.discard:
                if byte == ESCAPE and not self.escaped:
                    self.escaped = True
                    continue
                if self.escaped:
                    byte ^= 0x20
                    self.escaped = False
                if len(self.buffer) == MAX_FRAME_BYTES:
                    self.discard = True
                else:
                    # Start timeout on the first byte, not on a previous idle delimiter.
                    if not self.buffer:
                        self.started = now
                    self.buffer.append(byte)
        return frames

    def _reset(self, now):
        self.buffer.clear()
        self.escaped = self.discard = False
        self.started = now

    def _finish(self):
        body = bytes(self.buffer)
        if self.discard or self.escaped or len(body) < HEADER.size + CRC.size:
            self.rejected_frames += 1
            return None
        version, kind, session, sequence, length = HEADER.unpack_from(body)
        if (
            version != VERSION
            or length != len(body) - HEADER.size - CRC.size
            or checksum(body[:-2]) != CRC.unpack_from(body, len(body) - 2)[0]
        ):
            self.rejected_frames += 1
            return None
        return Frame(kind, session, sequence, body[HEADER.size : -2])
