"""Framing recovery and shared wire conventions without serial hardware."""

import struct

import pytest

from car.src.communication import protocol as wire


def test_fcs_reference_vector():
    assert wire.checksum(b"123456789") == 0x906E


def test_every_byte_round_trip_in_fragmented_frames():
    decoder = wire.Decoder(1)
    frames = [
        wire.Frame(99, 0x7E7D, n, bytes(range(n, n + 64))) for n in range(0, 256, 64)
    ]
    result = []
    for frame in frames:
        for byte in wire.encode(frame):
            result += decoder.feed(bytes([byte]), 0)
    assert result == frames


def test_corruption_oversize_and_dangling_escape_recover():
    valid = wire.Frame(1, 123, 0)
    encoded = bytearray(wire.encode(valid))
    encoded[2] ^= 1
    decoder = wire.Decoder(1)
    assert decoder.feed(bytes(encoded), 0) == []
    assert decoder.feed(b"\x7e" + b"x" * 200 + b"\x7e", 0) == []
    assert decoder.feed(b"\x7eabc\x7d\x7e", 0) == []
    assert decoder.feed(wire.encode(valid), 0) == [valid]
    assert decoder.rejected_frames == 3


def test_partial_frame_timeout_never_dispatches_trailing_bytes():
    frame = wire.encode(wire.Frame(1, 123, 0))
    decoder = wire.Decoder(0.1)
    assert decoder.feed(frame[:8], 0) == []
    assert decoder.feed(frame[8:], 1) == []
    assert decoder.feed(frame, 1) == [wire.Frame(1, 123, 0)]


@pytest.mark.parametrize(
    "sequence,previous,expected",
    [(0, 65535, True), (65535, 0, False), (1, 1, False), (32768, 0, False)],
)
def test_sequence_window(sequence, previous, expected):
    assert wire.newer(sequence, previous) is expected


def test_bad_length_with_valid_checksum_is_rejected():
    body = wire.HEADER.pack(wire.VERSION, 1, 123, 0, 1)
    packet = b"\x7e" + body + struct.pack("<H", wire.checksum(body)) + b"\x7e"
    assert wire.Decoder(1).feed(packet, 0) == []


def test_frame_size_limit():
    with pytest.raises(ValueError):
        wire.encode(wire.Frame(1, 123, 0, b"x" * wire.MAX_FRAME_BYTES))
