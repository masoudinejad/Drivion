"""Single Pydantic schema for the complete application configuration."""

import ipaddress
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from car.src.configuration.base import ConfigModel

PositiveRate = Annotated[float, Field(gt=0, allow_inf_nan=False)]


class EmptyConfig(ConfigModel):
    """Reject settings in sections whose schema has not been defined yet."""


class CameraConfig(ConfigModel):
    """Requested camera capture and persistence settings."""

    width: int = Field(gt=0, multiple_of=2)
    height: int = Field(gt=0, multiple_of=2)
    channels: Literal["rgb", "y"]
    file_format: Literal["numpy", "jpeg"]
    sensor_width: int = Field(gt=0, multiple_of=2)
    sensor_height: int = Field(gt=0, multiple_of=2)
    frame_rate: PositiveRate
    jpeg_quality: int = Field(ge=1, le=100)
    buffer_count: int = Field(ge=1, le=32)
    warmup_seconds: float = Field(ge=0, le=60, allow_inf_nan=False)


class PythonEnvironmentConfig(ConfigModel):
    """Existing system-managed Python environment settings."""

    name: str = Field(pattern=r"^[A-Za-z0-9_-]+$")
    path: str = Field(min_length=1)

    @model_validator(mode="after")
    def consistent_path(self):
        if Path(self.path).parts != ("system", "env", self.name):
            raise ValueError("path must be system/env/<name>")
        return self


class NetworkConfig(ConfigModel):
    """Wi-Fi client and fallback access-point settings."""

    command_path: str
    wifi_interface: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,15}$")
    fallback_profile: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
    fallback_ssid_prefix: str = Field(min_length=1, max_length=25)
    fallback_ssid_serial_characters: int = Field(ge=1, le=12)
    fallback_ipv4_address: str
    fallback_ipv4_prefix_length: int = Field(ge=8, le=30)
    fallback_delay_seconds: int = Field(ge=1, le=3600)
    fallback_timer_accuracy_seconds: int = Field(ge=1, le=3600)
    command_timeout_seconds: int = Field(ge=1, le=300)

    @field_validator("command_path")
    @classmethod
    def safe_command_path(cls, value):
        path = PurePosixPath(value)
        if (
            "\\" in value
            or any(character.isspace() for character in value)
            or not path.is_absolute()
            or ".." in path.parts
        ):
            raise ValueError("must be a safe absolute POSIX path")
        return value

    @field_validator("fallback_profile", "fallback_ssid_prefix")
    @classmethod
    def printable_ascii(cls, value):
        if not value.isascii() or not value.isprintable():
            raise ValueError("must contain printable ASCII characters")
        return value

    @field_validator("fallback_ipv4_address")
    @classmethod
    def valid_ipv4_address(cls, value):
        try:
            address = ipaddress.ip_address(value)
        except ValueError as error:
            raise ValueError("must be a valid IPv4 address") from error
        if address.version != 4:
            raise ValueError("must be an IPv4 address")
        return value

    @model_validator(mode="after")
    def valid_network(self):
        length = (
            len(self.fallback_ssid_prefix.encode())
            + 1
            + self.fallback_ssid_serial_characters
        )
        if length > 32:
            raise ValueError("fallback SSID exceeds 32 bytes")
        if self.fallback_timer_accuracy_seconds > self.fallback_delay_seconds:
            raise ValueError("fallback timer accuracy exceeds its delay")
        address = ipaddress.ip_address(self.fallback_ipv4_address)
        network = ipaddress.ip_network(
            f"{address}/{self.fallback_ipv4_prefix_length}", strict=False
        )
        if address in (network.network_address, network.broadcast_address):
            raise ValueError("fallback IPv4 address is not a usable host address")
        return self


class SystemConfig(ConfigModel):
    """Operating-system integration settings."""

    python_environment: PythonEnvironmentConfig
    network: NetworkConfig


class ArduinoConfig(ConfigModel):
    """User-selected Arduino port and repository sketchbook location."""

    address: str = Field(max_length=255)
    sketchbook_directory: str

    @field_validator("address")
    @classmethod
    def printable_address(cls, value):
        if value and not value.isprintable():
            raise ValueError("must contain printable characters")
        return value

    @field_validator("sketchbook_directory")
    @classmethod
    def safe_sketchbook_path(cls, value):
        path = PurePosixPath(value)
        if (
            not value
            or value == "."
            or "\\" in value
            or path.is_absolute()
            or ".." in path.parts
            or not path.is_relative_to(PurePosixPath("system/arduino"))
        ):
            raise ValueError("must be a safe path inside system/arduino")
        return value


class CommunicationConfig(ConfigModel):
    """Serial transport budgets; wire constants are versioned protocol definitions."""

    baud_rate: int = Field(ge=1, le=4000000)
    boot_wait_seconds: float = Field(ge=0, allow_inf_nan=False)
    read_timeout_seconds: float = Field(gt=0, allow_inf_nan=False)
    write_timeout_seconds: float = Field(gt=0, allow_inf_nan=False)
    handshake_timeout_seconds: float = Field(gt=0, allow_inf_nan=False)
    max_handshake_rtt_seconds: float = Field(gt=0, allow_inf_nan=False)
    frame_timeout_seconds: float = Field(gt=0, allow_inf_nan=False)
    status_stale_seconds: float = Field(gt=0, allow_inf_nan=False)
    command_validity_ms: int = Field(ge=1, le=2147483647)
    clock_drift_ppm: int = Field(ge=0, le=100000)
    max_session_age_seconds: float = Field(gt=0, allow_inf_nan=False)
    read_budget_bytes: int = Field(ge=1, le=65536)

    @model_validator(mode="after")
    def consistent_timing(self):
        if self.max_handshake_rtt_seconds >= self.command_validity_ms / 1000:
            raise ValueError("handshake uncertainty must be below command validity")
        if self.read_timeout_seconds > self.handshake_timeout_seconds:
            raise ValueError("read timeout exceeds handshake timeout")
        if self.max_handshake_rtt_seconds > self.handshake_timeout_seconds:
            raise ValueError("RTT limit exceeds handshake timeout")
        if self.frame_timeout_seconds < self.read_timeout_seconds:
            raise ValueError("frame timeout must accommodate serial read timeout")
        return self


class AppConfig(ConfigModel):
    """All supported sections in car/config.toml."""

    system: SystemConfig
    arduino: ArduinoConfig
    firmware: dict[str, dict[str, object]]
    camera: CameraConfig
    communication: CommunicationConfig
    joystick: EmptyConfig = Field(default_factory=EmptyConfig)
    drive: EmptyConfig = Field(default_factory=EmptyConfig)
    inference: EmptyConfig = Field(default_factory=EmptyConfig)
    recording: EmptyConfig = Field(default_factory=EmptyConfig)
    logging: EmptyConfig = Field(default_factory=EmptyConfig)

    @model_validator(mode="after")
    def valid_firmware_configuration(self):
        from car.system.arduino.firmware.definitions import validate_parameter_values

        try:
            validate_parameter_values(self.firmware)
        except TypeError as error:
            raise ValueError(str(error)) from error
        return self
