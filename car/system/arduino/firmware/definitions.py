"""Load firmware-owned requirements and validate central parameter values."""

import math
import re

import tomllib

from ..settings import load_context
from .identity import firmware_identity


def validate_fqbn(value):
    if not isinstance(value, str) or not re.fullmatch(
        r"[A-Za-z0-9_-]+:[A-Za-z0-9_-]+:[A-Za-z0-9_-]+(?::[A-Za-z0-9_=,.-]+)?", value
    ):
        raise ValueError("Firmware metadata must specify a valid board FQBN")


def validate_parameter_values(firmwares):
    """Keep application TOML limited to scalar defaults, not firmware metadata."""
    if not isinstance(firmwares, dict):
        raise TypeError("Firmware defaults must be a TOML table")
    for name, values in firmwares.items():
        if not isinstance(name, str) or not re.fullmatch(
            r"[A-Za-z][A-Za-z0-9_-]*", name
        ):
            raise ValueError("Firmware names must be safe identifiers")
        if not isinstance(values, dict):
            raise TypeError("Each firmware must contain its parameter defaults")
        for key, value in values.items():
            if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key) or key.startswith("DRIVION_"):
                raise ValueError(
                    "Firmware defaults must be uppercase parameter names, excluding DRIVION_"
                )
            if type(value) not in (str, bool, int, float):
                raise ValueError("Firmware defaults must be scalar values")
            if type(value) is float and not math.isfinite(value):
                raise ValueError("Firmware numeric defaults must be finite")


def resolve_firmware(definition, values):
    """Validate firmware-owned names/types/bounds against explicit user values."""
    if not isinstance(definition, dict) or set(definition) != {
        "firmware",
        "parameters",
    }:
        raise ValueError(
            "Firmware definition must contain firmware and parameters tables"
        )
    metadata, requirements = definition["firmware"], definition["parameters"]
    if not isinstance(metadata, dict) or set(metadata) != {
        "version",
        "protocol_version",
        "fqbn",
    }:
        raise ValueError(
            "Firmware metadata must contain version, protocol_version and fqbn"
        )
    firmware_identity("definition", metadata, {})
    validate_fqbn(metadata["fqbn"])
    if (
        not isinstance(requirements, dict)
        or not isinstance(values, dict)
        or set(values) != set(requirements)
    ):
        raise ValueError(
            "Firmware parameter values must exactly match its declared requirements"
        )
    validate_parameter_values({"definition": values})
    types = {"integer": int, "number": float, "boolean": bool, "string": str}
    for key, rule in requirements.items():
        if (
            not isinstance(rule, dict)
            or "type" not in rule
            or set(rule) - {"type", "minimum", "maximum"}
        ):
            raise ValueError(f"Invalid firmware parameter declaration: {key}")
        kind = rule["type"]
        if not isinstance(kind, str) or kind not in types:
            raise ValueError(f"Invalid firmware parameter type: {key}")
        value = values[key]
        accepted = (int, float) if kind == "number" else (types[kind],)
        if type(value) not in accepted:
            raise ValueError(f"{key} must be {kind}")
        lower, upper = (
            (-(2**31), 2**32 - 1)
            if kind == "integer"
            else (-3.402823466e38, 3.402823466e38)
        )
        if kind in ("integer", "number") and (
            not lower <= value <= upper or not math.isfinite(value)
        ):
            raise ValueError(f"{key} is outside the supported AVR numeric range")
        if kind == "string" and (not value.isascii() or "\x00" in value):
            raise ValueError(f"{key} must be an ASCII string without NUL")
        for bound in ("minimum", "maximum"):
            if bound in rule:
                limit = rule[bound]
                if (
                    kind not in ("integer", "number")
                    or type(limit)
                    not in ((int,) if kind == "integer" else (int, float))
                    or not math.isfinite(limit)
                ):
                    raise ValueError(f"Invalid {bound} constraint for {key}")
                if (bound == "minimum" and value < limit) or (
                    bound == "maximum" and value > limit
                ):
                    raise ValueError(f"{key} violates its firmware-defined {bound}")
        if (
            "minimum" in rule
            and "maximum" in rule
            and rule["minimum"] > rule["maximum"]
        ):
            raise ValueError(f"Invalid firmware bounds for {key}")
    return {**metadata, "parameters": dict(values)}


def load_firmware(name, car_root, values=None, *, context=None):
    """Read a sketch's own definition and validate its central parameter values."""
    context = context or load_context(car_root)
    if values is None:
        if name not in context.firmware_defaults:
            raise ValueError(f"Unknown firmware: {name}")
        values = context.firmware_defaults[name]
    validate_parameter_values({name: values})
    settings = context.compile_settings
    sketchbook = context.directory(context.runtime.sketchbook_directory)
    source = (sketchbook / name).resolve()
    if not source.is_relative_to(sketchbook):
        raise ValueError("Firmware definition must remain inside the sketchbook")
    path = source / settings["definition_filename"]
    if path.is_symlink():
        raise ValueError("Firmware definition must not be a symlink")
    with path.open("rb") as stream:
        definition = tomllib.load(stream)
    return resolve_firmware(definition, values)
