"""Load and validate the central application configuration."""

from pathlib import Path

import tomllib
from pydantic import Field

from car.src.camera.config import CameraConfig
from car.src.configuration.base import ConfigModel


class EmptyConfig(ConfigModel):
    """Reject settings in sections whose schema has not been defined yet."""


class PythonEnvironmentConfig(ConfigModel):
    """Existing system-managed Python environment settings."""

    name: str = Field(min_length=1)
    path: str = Field(min_length=1)


class SystemConfig(ConfigModel):
    """System-managed Python environment settings."""

    python_environment: PythonEnvironmentConfig


class ArduinoConfig(ConfigModel):
    """Reserved Arduino sections."""

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
