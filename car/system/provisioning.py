"""Read and validate system provisioning settings from the project metadata."""

import re
from pathlib import Path

import tomllib


def system_settings(car_root):
    with (Path(car_root) / "system/pyproject.toml").open("rb") as stream:
        system = (
            tomllib.load(stream)
            .get("tool", {})
            .get("drivion", {})
            .get("provisioning", {})
        )
    packages = system.get("packages")
    modules = system.get("system_imports")
    for name, values, pattern in (
        ("packages", packages, r"[a-z0-9][a-z0-9+.-]+(?::[a-z0-9-]+)?"),
        ("system_imports", modules, r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*"),
    ):
        if not isinstance(values, list) or any(
            not isinstance(value, str) or not re.fullmatch(pattern, value)
            for value in values
        ):
            raise ValueError(
                f"Configure tool.drivion.provisioning.{name} as a list of valid names"
            )
    return packages, modules


def verification_timeout(car_root):
    """Read the bounded dependency-import timeout from project metadata."""
    with (Path(car_root) / "system/pyproject.toml").open("rb") as stream:
        value = (
            tomllib.load(stream)
            .get("tool", {})
            .get("drivion", {})
            .get("verification", {})
            .get("command_timeout_seconds")
        )
    if type(value) is not int or not 1 <= value <= 600:
        raise ValueError(
            "Configure tool.drivion.verification.command_timeout_seconds "
            "between 1 and 600"
        )
    return value
