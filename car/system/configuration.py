"""Read bootstrap settings without the car Python environment.

The application owns the single Pydantic schema. These standard-library readers
exist because provisioning and boot services run before that environment exists.
Runtime choices come from ``config.toml``; tool metadata comes from
``system/pyproject.toml``.
"""

import ipaddress
import re
from dataclasses import dataclass, fields
from pathlib import Path, PurePosixPath

import tomllib


@dataclass(frozen=True)
class ArduinoSettings:
    """User-selected Arduino connection and sketchbook settings."""

    address: str
    sketchbook_directory: str


@dataclass(frozen=True)
class ArduinoToolchainSettings:
    """Pinned Arduino provisioning and discovery metadata."""

    cli_version: str
    cli_archive_name: str
    cli_archive_sha256: str
    cli_release_url: str
    cli_install_directory: str
    cli_archive_executable: str
    cli_executable_path: str
    data_directory: str
    download_directory: str
    config_path: str
    service_config_path: str
    serial_group: str
    avr_core: str
    avr_core_version: str
    discovery_timeout_seconds: int
    command_timeout_seconds: int


@dataclass(frozen=True)
class NetworkSettings:
    """Wi-Fi client and fallback access-point settings."""

    command_path: str
    wifi_interface: str
    fallback_profile: str
    fallback_ssid_prefix: str
    fallback_ssid_serial_characters: int
    fallback_ipv4_address: str
    fallback_ipv4_prefix_length: int
    fallback_delay_seconds: int
    fallback_timer_accuracy_seconds: int
    command_timeout_seconds: int

    @property
    def fallback_ipv4_cidr(self):
        return f"{self.fallback_ipv4_address}/{self.fallback_ipv4_prefix_length}"

    def fallback_ssid(self, serial):
        compact = "".join(character for character in serial if character.isalnum())
        suffix = compact[-self.fallback_ssid_serial_characters :]
        if len(suffix) != self.fallback_ssid_serial_characters:
            raise ValueError("Raspberry Pi serial number is too short for the SSID")
        return f"{self.fallback_ssid_prefix}-{suffix.upper()}"


@dataclass(frozen=True)
class PythonEnvironmentSettings:
    """Existing system-managed Python environment settings."""

    name: str
    path: str


@dataclass(frozen=True)
class ExecutionSettings:
    """Resource bounds used while provisioning and verifying the runtime."""

    apt_lock_timeout_seconds: int
    uv_concurrent_downloads: int
    uv_concurrent_builds: int
    uv_concurrent_installs: int
    numerical_thread_limit: int


@dataclass(frozen=True)
class ServiceSettings:
    """Root-owned service installation paths."""

    python_executable: str
    library_directory: str
    configuration_directory: str
    unit_directory: str
    reboot_required_path: str
    temporary_directory: str


@dataclass(frozen=True)
class UvSettings:
    """Official uv installer channel and system executable location."""

    installer_url: str
    executable_directory: str


def _load_toml(path):
    with Path(path).open("rb") as stream:
        return tomllib.load(stream)


def _config_table(car_root, name):
    values = _load_toml(Path(car_root) / "config.toml").get(name)
    if values is None:
        raise ValueError(f"Configure the {name} table in car/config.toml")
    if not isinstance(values, dict):
        raise TypeError(f"Configure the {name} table in car/config.toml")
    return values


def _tool_table(car_root, name):
    values = (
        _load_toml(Path(car_root) / "system/pyproject.toml")
        .get("tool", {})
        .get("drivion", {})
        .get(name)
    )
    if values is None:
        raise ValueError(f"Configure tool.drivion.{name} in system/pyproject.toml")
    if not isinstance(values, dict):
        raise TypeError(f"Configure tool.drivion.{name} in system/pyproject.toml")
    return values


def _exact_settings(model, values, label):
    expected = {field.name for field in fields(model)}
    if set(values) != expected:
        raise ValueError(f"Configure exactly the supported {label} settings")
    return model(**values)


def _safe_absolute_path(value, label):
    if not isinstance(value, str):
        raise TypeError(f"{label} must be a string")
    path = PurePosixPath(value)
    if (
        "\\" in value
        or any(character.isspace() for character in value)
        or not path.is_absolute()
        or ".." in path.parts
    ):
        raise ValueError(f"{label} must be a safe absolute POSIX path")
    return path


def _safe_relative_path(value, label):
    if not isinstance(value, str):
        raise TypeError(f"{label} must be a string")
    path = PurePosixPath(value)
    if (
        not value
        or value == "."
        or "\\" in value
        or path.is_absolute()
        or ".." in path.parts
    ):
        raise ValueError(f"{label} must be a safe relative POSIX path")
    return path


def arduino_settings(car_root, *, values=None):
    """Read the two user-configurable Arduino settings."""
    settings = _exact_settings(
        ArduinoSettings,
        _config_table(car_root, "arduino") if values is None else values,
        "arduino",
    )
    if (
        not isinstance(settings.address, str)
        or len(settings.address) > 255
        or (settings.address and not settings.address.isprintable())
    ):
        raise ValueError("Configure a printable arduino.address")
    sketchbook = _safe_relative_path(
        settings.sketchbook_directory, "arduino.sketchbook_directory"
    )
    if not sketchbook.is_relative_to(PurePosixPath("system/arduino")):
        raise ValueError("arduino.sketchbook_directory must be inside system/arduino")
    return settings


def arduino_toolchain_settings(car_root, *, values=None):
    """Read pinned Arduino toolchain metadata from project TOML."""
    settings = _exact_settings(
        ArduinoToolchainSettings,
        _tool_table(car_root, "arduino") if values is None else values,
        "tool.drivion.arduino",
    )
    for name in ("cli_version", "avr_core_version"):
        value = getattr(settings, name)
        if not isinstance(value, str) or not re.fullmatch(r"\d+\.\d+\.\d+", value):
            raise ValueError(f"Configure a valid tool.drivion.arduino.{name}")
    if not isinstance(settings.cli_archive_name, str) or not re.fullmatch(
        r"[A-Za-z0-9_.-]+", settings.cli_archive_name
    ):
        raise ValueError("Configure a valid Arduino CLI archive name")
    if not isinstance(settings.cli_archive_sha256, str) or not re.fullmatch(
        r"[0-9a-f]{64}", settings.cli_archive_sha256
    ):
        raise ValueError("Configure a valid Arduino CLI archive checksum")
    if not isinstance(
        settings.cli_release_url, str
    ) or not settings.cli_release_url.startswith("https://"):
        raise ValueError("Configure a secure Arduino CLI release URL")
    for name in (
        "cli_install_directory",
        "cli_executable_path",
        "service_config_path",
    ):
        _safe_absolute_path(getattr(settings, name), f"tool.drivion.arduino.{name}")
    if not isinstance(settings.cli_archive_executable, str) or not re.fullmatch(
        r"[A-Za-z0-9_.-]+", settings.cli_archive_executable
    ):
        raise ValueError("Configure a valid Arduino archive executable name")
    if not isinstance(settings.serial_group, str) or not re.fullmatch(
        r"[a-z_][a-z0-9_-]*", settings.serial_group
    ):
        raise ValueError("Configure a valid Arduino serial group")
    if not isinstance(settings.avr_core, str) or not re.fullmatch(
        r"[a-z0-9_-]+:[a-z0-9_-]+", settings.avr_core
    ):
        raise ValueError("Configure a valid Arduino core identifier")
    paths = {
        name: _safe_relative_path(
            getattr(settings, name), f"tool.drivion.arduino.{name}"
        )
        for name in ("data_directory", "download_directory", "config_path")
    }
    if not paths["download_directory"].is_relative_to(paths["data_directory"]):
        raise ValueError("Arduino download_directory must be inside data_directory")
    if paths["config_path"].parent != paths["data_directory"]:
        raise ValueError("Arduino config_path must be directly inside data_directory")
    wait = settings.discovery_timeout_seconds
    timeout = settings.command_timeout_seconds
    if (
        type(wait) is not int
        or type(timeout) is not int
        or not 1 <= wait <= 300
        or not wait < timeout <= 600
    ):
        raise ValueError("Configure valid Arduino discovery timeouts")
    return settings


def network_settings(car_root):
    """Read and validate fallback Wi-Fi runtime settings."""
    values = _config_table(car_root, "system").get("network")
    if values is None:
        raise ValueError("Configure system.network in car/config.toml")
    if not isinstance(values, dict):
        raise TypeError("Configure system.network in car/config.toml")
    settings = _exact_settings(NetworkSettings, values, "system.network")
    _safe_absolute_path(settings.command_path, "system.network.command_path")
    if not isinstance(settings.wifi_interface, str) or not re.fullmatch(
        r"[A-Za-z0-9_.-]{1,15}", settings.wifi_interface
    ):
        raise ValueError("Configure a valid system.network.wifi_interface")
    for name, value, maximum in (
        ("fallback_profile", settings.fallback_profile, 64),
        ("fallback_ssid_prefix", settings.fallback_ssid_prefix, 25),
    ):
        if (
            not isinstance(value, str)
            or not value.isascii()
            or not value.isprintable()
            or not 1 <= len(value) <= maximum
        ):
            raise ValueError(f"Configure a valid system.network.{name}")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", settings.fallback_profile):
        raise ValueError("Configure a valid system.network.fallback_profile")
    serial_characters = settings.fallback_ssid_serial_characters
    if (
        type(serial_characters) is not int
        or not 1 <= serial_characters <= 12
        or len(settings.fallback_ssid_prefix.encode()) + 1 + serial_characters > 32
    ):
        raise ValueError("The configured fallback SSID would be invalid")
    try:
        address = ipaddress.ip_address(settings.fallback_ipv4_address)
    except ValueError as error:
        raise ValueError("Configure a valid fallback IPv4 address") from error
    if address.version != 4:
        raise ValueError("The fallback address must be IPv4")
    prefix = settings.fallback_ipv4_prefix_length
    if type(prefix) is not int or not 8 <= prefix <= 30:
        raise ValueError("The fallback IPv4 prefix length must be between 8 and 30")
    network = ipaddress.ip_network(settings.fallback_ipv4_cidr, strict=False)
    if address in (network.network_address, network.broadcast_address):
        raise ValueError("The fallback IPv4 address must be a usable host address")
    delay = settings.fallback_delay_seconds
    accuracy = settings.fallback_timer_accuracy_seconds
    if type(delay) is not int or not 1 <= delay <= 3600:
        raise ValueError("The fallback delay must be between 1 and 3600 seconds")
    if type(accuracy) is not int or not 1 <= accuracy <= delay:
        raise ValueError("The fallback timer accuracy must be within its delay")
    timeout = settings.command_timeout_seconds
    if type(timeout) is not int or not 1 <= timeout <= 300:
        raise ValueError(
            "The network command timeout must be between 1 and 300 seconds"
        )
    return settings


def execution_settings(car_root):
    """Read bounded provisioning concurrency and timeout settings."""
    settings = _exact_settings(
        ExecutionSettings,
        _tool_table(car_root, "execution"),
        "tool.drivion.execution",
    )
    for field in fields(ExecutionSettings):
        value = getattr(settings, field.name)
        if type(value) is not int or not 1 <= value <= 600:
            raise ValueError(
                f"tool.drivion.execution.{field.name} must be between 1 and 600"
            )
    return settings


def python_environment_settings(car_root):
    """Read and validate the named in-project Python environment."""
    values = _config_table(car_root, "system").get("python_environment")
    if values is None:
        raise ValueError("Configure system.python_environment in car/config.toml")
    if not isinstance(values, dict):
        raise TypeError("Configure system.python_environment in car/config.toml")
    settings = _exact_settings(
        PythonEnvironmentSettings, values, "system.python_environment"
    )
    if not isinstance(settings.name, str) or not re.fullmatch(
        r"[A-Za-z0-9_-]+", settings.name
    ):
        raise ValueError("Configure a valid system.python_environment.name")
    path = Path(settings.path) if isinstance(settings.path, str) else Path()
    if path.is_absolute() or path.parts != ("system", "env", settings.name):
        raise ValueError("The environment path must be system/env/<name>")
    return settings


def service_settings(car_root):
    """Read and validate protected-service installation paths."""
    settings = _exact_settings(
        ServiceSettings, _tool_table(car_root, "services"), "tool.drivion.services"
    )
    for field in fields(ServiceSettings):
        _safe_absolute_path(
            getattr(settings, field.name), f"tool.drivion.services.{field.name}"
        )
    return settings


def uv_settings(car_root):
    """Read and validate the official uv update channel settings."""
    settings = _exact_settings(
        UvSettings, _tool_table(car_root, "uv"), "tool.drivion.uv"
    )
    if not isinstance(
        settings.installer_url, str
    ) or not settings.installer_url.startswith("https://"):
        raise ValueError("Configure a secure tool.drivion.uv.installer_url")
    _safe_absolute_path(
        settings.executable_directory, "tool.drivion.uv.executable_directory"
    )
    return settings
