"""Load and validate the central application configuration."""

import os
import tempfile
from pathlib import Path

import tomlkit
import tomllib

from car.src.configuration.schema import AppConfig


def load_config(path: str | Path | None = None) -> AppConfig:
    """Read TOML once and validate every section before initializing components."""
    config_path = (
        Path(path) if path is not None else Path(__file__).parents[1] / "config.toml"
    )
    with config_path.open("rb") as stream:
        values = tomllib.load(stream)
    return AppConfig.model_validate(values)


def update_config(
    parameter: str, value: object, path: str | Path | None = None
) -> AppConfig:
    """Persist an existing dotted setting and return the validated configuration.

    For example, ``update_config("camera.frame_rate", 30.0)`` updates the
    central car/config.toml. Comments and unrelated settings are preserved.
    Unknown settings raise KeyError; invalid values raise ValidationError.
    Existing in-memory configurations must be reloaded by their callers.
    Callers must serialize concurrent updates to avoid losing changes.
    """
    config_path = (
        Path(path) if path is not None else Path(__file__).parents[1] / "config.toml"
    ).resolve(strict=True)
    document = tomlkit.parse(config_path.read_text(encoding="utf-8"))
    parts = parameter.split(".")
    table = document
    for part in parts[:-1]:
        if not part or part not in table or not isinstance(table[part], dict):
            raise KeyError(parameter)
        table = table[part]
    key = parts[-1]
    if not key or key not in table or isinstance(table[key], dict):
        raise KeyError(parameter)
    # Validate the Python value before serialization, so TOML cannot coerce it.
    values = document.unwrap()
    target = values
    for part in parts[:-1]:
        target = target[part]
    target[key] = value
    AppConfig.model_validate(values)
    table[key] = value
    contents = tomlkit.dumps(document)
    config = AppConfig.model_validate(tomllib.loads(contents))
    # Replace atomically: a failed write must not truncate the live configuration.
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=config_path.parent, delete=False
        ) as stream:
            temporary_path = Path(stream.name)
            stream.write(contents)
            stream.flush()
            os.fchmod(stream.fileno(), config_path.stat().st_mode & 0o777)
            os.fsync(stream.fileno())
        os.replace(temporary_path, config_path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return config
