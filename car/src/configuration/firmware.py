"""Shared validation of firmware parameter values, independent of tooling."""

import math
import re


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
