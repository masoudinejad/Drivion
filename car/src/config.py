"""Load and validate the central application configuration."""

import ipaddress
from pathlib import Path, PurePosixPath

import tomllib
from pydantic import Field, field_validator, model_validator

from car.src.camera.config import CameraConfig
from car.src.configuration.base import ConfigModel


class EmptyConfig(ConfigModel):
    """Reject settings in sections whose schema has not been defined yet."""


class PythonEnvironmentConfig(ConfigModel):
    """Existing system-managed Python environment settings."""

    name: str = Field(min_length=1)
    path: str = Field(min_length=1)


class NetworkConfig(ConfigModel):
    """Wi-Fi client and fallback access-point settings."""

    wifi_interface: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,15}$")
    fallback_profile: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
    fallback_ssid_prefix: str = Field(min_length=1, max_length=25)
    fallback_ssid_serial_characters: int = Field(ge=1, le=12)
    fallback_ipv4_address: str
    fallback_ipv4_prefix_length: int = Field(ge=8, le=30)
    fallback_delay_seconds: int = Field(ge=1, le=3600)
    fallback_timer_accuracy_seconds: int = Field(ge=1, le=3600)

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


class UvProvisioningConfig(ConfigModel):
    """Pinned uv release installed on the Raspberry Pi."""

    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    archive_name: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    archive_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    release_url: str = Field(pattern=r"^https://")
    install_directory: str
    executable_directory: str

    @field_validator("install_directory", "executable_directory")
    @classmethod
    def safe_absolute_directory(cls, value):
        path = PurePosixPath(value)
        if "\\" in value or not path.is_absolute() or ".." in path.parts:
            raise ValueError("must be a safe absolute POSIX path")
        return value


class SystemProvisioningConfig(ConfigModel):
    """Pinned system tools installed during provisioning."""

    uv: UvProvisioningConfig


class SystemConfig(ConfigModel):
    """Operating-system integration settings."""

    python_environment: PythonEnvironmentConfig
    network: NetworkConfig
    provisioning: SystemProvisioningConfig


class ArduinoProvisioningConfig(ConfigModel):
    """Arduino CLI installation and Raspberry Pi path settings."""

    cli_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    cli_archive_name: str = Field(min_length=1)
    cli_archive_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    cli_release_url: str = Field(pattern=r"^https://")
    cli_install_directory: str
    cli_archive_executable: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    cli_executable_path: str
    data_directory: str
    download_directory: str
    config_path: str
    sketchbook_directory: str
    serial_group: str = Field(pattern=r"^[a-z_][a-z0-9_-]*$")
    avr_core: str = Field(pattern=r"^[a-z0-9_-]+:[a-z0-9_-]+$")
    avr_core_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")

    @field_validator(
        "data_directory",
        "download_directory",
        "config_path",
        "sketchbook_directory",
    )
    @classmethod
    def require_safe_relative_path(cls, value):
        path = PurePosixPath(value)
        if (
            not value
            or value == "."
            or "\\" in value
            or path.is_absolute()
            or ".." in path.parts
        ):
            raise ValueError("must be a safe relative POSIX path")
        return value

    @field_validator("cli_install_directory", "cli_executable_path")
    @classmethod
    def require_absolute_install_directory(cls, value):
        path = PurePosixPath(value)
        if "\\" in value or not path.is_absolute() or ".." in path.parts:
            raise ValueError("must be a safe absolute POSIX path")
        return value

    @model_validator(mode="after")
    def require_consistent_paths(self):
        data = PurePosixPath(self.data_directory)
        if not PurePosixPath(self.download_directory).is_relative_to(data):
            raise ValueError("download_directory must be inside data_directory")
        if PurePosixPath(self.config_path).parent != data:
            raise ValueError("config_path must be directly inside data_directory")
        if not PurePosixPath(self.sketchbook_directory).is_relative_to(
            PurePosixPath("system/arduino")
        ):
            raise ValueError("sketchbook_directory must be inside system/arduino")
        return self


class ArduinoConfig(ConfigModel):
    """Arduino runtime and provisioning settings."""

    provisioning: ArduinoProvisioningConfig | None = None
    communication: EmptyConfig = Field(default_factory=EmptyConfig)
    flashing: EmptyConfig = Field(default_factory=EmptyConfig)


class AppConfig(ConfigModel):
    """All supported sections in car/config.toml."""

    system: SystemConfig | None = None
    arduino: ArduinoConfig = Field(default_factory=ArduinoConfig)
    camera: CameraConfig = Field(default_factory=CameraConfig)
    joystick: EmptyConfig = Field(default_factory=EmptyConfig)
    drive: EmptyConfig = Field(default_factory=EmptyConfig)
    inference: EmptyConfig = Field(default_factory=EmptyConfig)
    recording: EmptyConfig = Field(default_factory=EmptyConfig)
    logging: EmptyConfig = Field(default_factory=EmptyConfig)


def load_config(path: str | Path | None = None) -> AppConfig:
    """Read TOML once and validate every section before initializing components."""
    config_path = (
        Path(path) if path is not None else Path(__file__).parents[1] / "config.toml"
    )
    with config_path.open("rb") as stream:
        values = tomllib.load(stream)
    return AppConfig.model_validate(values)
