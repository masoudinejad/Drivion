"""Resolve the central configuration's named Python environment."""

import re
from pathlib import Path

import tomllib


def environment_path(car_root):
    car_root = Path(car_root).resolve()
    with (car_root / "config.toml").open("rb") as stream:
        settings = tomllib.load(stream).get("system", {}).get("python_environment", {})
    name, path = settings.get("name"), settings.get("path")
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", name):
        raise ValueError("Configure a valid system.python_environment.name")
    if not isinstance(path, str) or Path(path).is_absolute():
        raise ValueError("The environment path must be relative to car/")
    if Path(path).parts != ("system", "env", name):
        raise ValueError("The environment path must be system/env/<name>")
    target = (car_root / path).resolve()
    if not target.is_relative_to(car_root):
        raise ValueError("The environment path must stay inside car/")
    return target


if __name__ == "__main__":
    import sys

    try:
        print(environment_path(sys.argv[1]))
    except (KeyError, OSError, ValueError) as error:
        print(f"Environment configuration error: {error}", file=sys.stderr)
        sys.exit(1)
