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
