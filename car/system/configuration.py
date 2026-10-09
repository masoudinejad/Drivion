"""Read system settings from the central car configuration."""

import ipaddress
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import tomllib


@dataclass(frozen=True)
class ArduinoSettings:
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
    sketchbook_directory: str
    serial_group: str
    avr_core: str
    avr_core_version: str


@dataclass(frozen=True)
class NetworkSettings:
    wifi_interface: str
    fallback_profile: str
    fallback_ssid_prefix: str
    fallback_ssid_serial_characters: int
    fallback_ipv4_address: str
    fallback_ipv4_prefix_length: int
    fallback_delay_seconds: int
    fallback_timer_accuracy_seconds: int

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
class UvSettings:
    version: str
    archive_name: str
    archive_sha256: str
    release_url: str
    install_directory: str
    executable_directory: str


@dataclass(frozen=True)
class PythonEnvironmentSettings:
    name: str
    path: str


def _system_table(car_root):
    with (Path(car_root) / "config.toml").open("rb") as stream:
        system = tomllib.load(stream).get("system")
    if not isinstance(system, dict):
        raise ValueError(  # noqa: TRY004 - invalid persisted configuration
            "Configure the system table in car/config.toml"
        )
    return system


def arduino_settings(car_root):
    with (Path(car_root) / "config.toml").open("rb") as stream:
        arduino = tomllib.load(stream).get("arduino")
    values = arduino.get("provisioning") if isinstance(arduino, dict) else None
    if (
        not isinstance(values, dict)
        or set(values) != set(ArduinoSettings.__dataclass_fields__)
        or any(not isinstance(value, str) for value in values.values())
    ):
        raise ValueError(
            "Configure exactly the supported arduino.provisioning settings in "
            "car/config.toml"
        )
    settings = ArduinoSettings(**values)
    for name in ("cli_version", "avr_core_version"):
        if not re.fullmatch(r"\d+\.\d+\.\d+", getattr(settings, name)):
            raise ValueError(f"Configure a valid arduino.provisioning.{name}")
    if not re.fullmatch(r"[0-9a-f]{64}", settings.cli_archive_sha256):
        raise ValueError("Configure a valid arduino.provisioning.cli_archive_sha256")
    if not settings.cli_archive_name or not settings.cli_release_url.startswith(
        "https://"
    ):
        raise ValueError("Configure valid Arduino CLI release information")
    for name in ("cli_install_directory", "cli_executable_path"):
        value = getattr(settings, name)
        path = PurePosixPath(value)
        if "\\" in value or not path.is_absolute() or ".." in path.parts:
            raise ValueError(f"arduino.provisioning.{name} must be absolute")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", settings.cli_archive_executable):
        raise ValueError("Configure a valid Arduino archive executable name")
    if not re.fullmatch(r"[a-z_][a-z0-9_-]*", settings.serial_group):
        raise ValueError("Configure a valid Arduino serial group")
    if not re.fullmatch(r"[a-z0-9_-]+:[a-z0-9_-]+", settings.avr_core):
        raise ValueError("Configure a valid Arduino core identifier")
    relative_paths = {
        name: PurePosixPath(getattr(settings, name))
        for name in (
            "data_directory",
            "download_directory",
            "config_path",
            "sketchbook_directory",
        )
    }
    if any(
        not str(path)
        or str(path) == "."
        or "\\" in getattr(settings, name)
        or path.is_absolute()
        or ".." in path.parts
        for name, path in relative_paths.items()
    ):
        raise ValueError("Arduino user and car paths must be safe relative paths")
    data = relative_paths["data_directory"]
    if not relative_paths["download_directory"].is_relative_to(data):
        raise ValueError("Arduino download_directory must be inside data_directory")
    if relative_paths["config_path"].parent != data:
        raise ValueError("Arduino config_path must be inside data_directory")
    if not relative_paths["sketchbook_directory"].is_relative_to(
        PurePosixPath("system/arduino")
    ):
        raise ValueError("Arduino sketchbook_directory must be inside system/arduino")
    return settings


def network_settings(car_root):
    values = _system_table(car_root).get("network")
    if not isinstance(values, dict):
        raise ValueError(  # noqa: TRY004 - invalid persisted configuration
            "Configure system.network in car/config.toml"
        )
    expected = set(NetworkSettings.__dataclass_fields__)
    if set(values) != expected:
        raise ValueError(
            "Configure exactly the supported system.network settings in car/config.toml"
        )
    settings = NetworkSettings(**values)
    if not isinstance(settings.wifi_interface, str) or not re.fullmatch(
        r"[A-Za-z0-9_.-]{1,15}", settings.wifi_interface
    ):
        raise ValueError("Configure a valid system.network.wifi_interface")
    for name, value, maximum in (
        ("fallback_profile", settings.fallback_profile, 64),
        ("fallback_ssid_prefix", settings.fallback_ssid_prefix, 25),
    ):
        if not isinstance(value, str) or not value.isascii() or not value.isprintable():
            raise ValueError(f"Configure a printable ASCII system.network.{name}")
        if not 1 <= len(value) <= maximum:
            raise ValueError(f"Configure a valid system.network.{name}")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", settings.fallback_profile):
        raise ValueError("Configure a valid system.network.fallback_profile")
    serial_characters = settings.fallback_ssid_serial_characters
    if (
        isinstance(serial_characters, bool)
        or not isinstance(serial_characters, int)
        or not 1 <= serial_characters <= 12
        or len(settings.fallback_ssid_prefix.encode()) + 1 + serial_characters > 32
    ):
        raise ValueError("The configured fallback SSID would be invalid")
    if not isinstance(settings.fallback_ipv4_address, str):
        raise ValueError(  # noqa: TRY004 - invalid persisted configuration
            "Configure a valid system.network.fallback_ipv4_address"
        )
    try:
        address = ipaddress.ip_address(settings.fallback_ipv4_address)
    except ValueError as error:
        raise ValueError(
            "Configure a valid system.network.fallback_ipv4_address"
        ) from error
    if address.version != 4:
        raise ValueError("The fallback address must be IPv4")
    prefix_length = settings.fallback_ipv4_prefix_length
    if (
        isinstance(prefix_length, bool)
        or not isinstance(prefix_length, int)
        or not 8 <= prefix_length <= 30
    ):
        raise ValueError("The fallback IPv4 prefix length must be between 8 and 30")
    network = ipaddress.ip_network(settings.fallback_ipv4_cidr, strict=False)
    if address in (network.network_address, network.broadcast_address):
        raise ValueError("The fallback IPv4 address must be a usable host address")
    delay = settings.fallback_delay_seconds
    if isinstance(delay, bool) or not isinstance(delay, int) or not 1 <= delay <= 3600:
        raise ValueError("The fallback delay must be between 1 and 3600 seconds")
    accuracy = settings.fallback_timer_accuracy_seconds
    if (
        isinstance(accuracy, bool)
        or not isinstance(accuracy, int)
        or not 1 <= accuracy <= delay
    ):
        raise ValueError("The fallback timer accuracy must be within its delay")
    return settings


def python_environment_settings(car_root):
    values = _system_table(car_root).get("python_environment")
    if (
        not isinstance(values, dict)
        or set(values) != set(PythonEnvironmentSettings.__dataclass_fields__)
        or any(not isinstance(value, str) for value in values.values())
    ):
        raise ValueError(
            "Configure exactly the supported system.python_environment settings "
            "in car/config.toml"
        )
    settings = PythonEnvironmentSettings(**values)
    if not re.fullmatch(r"[A-Za-z0-9_-]+", settings.name):
        raise ValueError("Configure a valid system.python_environment.name")
    path = Path(settings.path)
    if path.is_absolute() or path.parts != ("system", "env", settings.name):
        raise ValueError("The environment path must be system/env/<name>")
    return settings


def uv_settings(car_root):
    values = _system_table(car_root).get("provisioning", {}).get("uv")
    if not isinstance(values, dict) or set(values) != set(
        UvSettings.__dataclass_fields__
    ):
        raise ValueError(
            "Configure exactly the supported system.provisioning.uv settings in "
            "car/config.toml"
        )
    settings = UvSettings(**values)
    if not re.fullmatch(r"\d+\.\d+\.\d+", settings.version):
        raise ValueError("Configure a valid system.provisioning.uv.version")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", settings.archive_name):
        raise ValueError("Configure a valid system.provisioning.uv.archive_name")
    if not re.fullmatch(r"[0-9a-f]{64}", settings.archive_sha256):
        raise ValueError("Configure a valid system.provisioning.uv.archive_sha256")
    if not settings.release_url.startswith("https://"):
        raise ValueError("Configure a secure system.provisioning.uv.release_url")
    for name in ("install_directory", "executable_directory"):
        value = getattr(settings, name)
        path = PurePosixPath(value)
        if "\\" in value or not path.is_absolute() or ".." in path.parts:
            raise ValueError(f"Configure a safe absolute system.provisioning.uv.{name}")
    return settings
