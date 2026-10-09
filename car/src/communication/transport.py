"""Byte transport boundary. Import pyserial only when opening real hardware."""

from typing import Protocol

from car.src.configuration.schema import CommunicationConfig


class ByteTransport(Protocol):
    """A bounded-read, bounded-write transport owned by one communication client."""

    def read(self, size: int) -> bytes: ...
    def write(self, data: bytes) -> int: ...
    def close(self) -> None: ...


def open_serial(address: str, config: CommunicationConfig) -> ByteTransport:
    """Open the selected port exclusively; ambiguous auto-discovery is rejected."""
    import serial
    from serial.tools.list_ports import comports

    if address == "auto":
        ports = list(comports())
        if len(ports) != 1:
            raise ValueError(
                "auto requires exactly one serial port; configure arduino.address"
            )
        address = ports[0].device
    if not address:
        raise ValueError("configure arduino.address before connecting")
    return serial.Serial(
        port=address,
        baudrate=config.baud_rate,
        timeout=config.read_timeout_seconds,
        write_timeout=config.write_timeout_seconds,
        exclusive=True,
    )
