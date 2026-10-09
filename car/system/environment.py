"""Resolve the central configuration's named Python environment."""

import os
import sys
from pathlib import Path

if __package__:
    from .configuration import python_environment_settings
else:
    from configuration import python_environment_settings


def environment_path(car_root):
    car_root = Path(car_root).resolve()
    settings = python_environment_settings(car_root)
    target = (car_root / settings.path).resolve()
    if not target.is_relative_to(car_root):
        raise ValueError("The environment path must stay inside car/")
    return target


def enter_environment(car_root, entry_point):
    """Re-execute a launcher with the centrally configured Python environment."""
    target = environment_path(car_root)
    if Path(sys.prefix).resolve() == target:
        return
    python = target / "bin/python"
    if not python.is_file():
        raise ValueError(
            "The car environment is missing. Run Ansible provisioning first."
        )
    environment = os.environ.copy()
    environment.pop("PYTHONHOME", None)
    environment.pop("PYTHONPATH", None)
    os.execve(
        str(python),
        [str(python), str(Path(entry_point).resolve()), *sys.argv[1:]],
        environment,
    )


if __name__ == "__main__":
    try:
        print(environment_path(sys.argv[1]))
    except (KeyError, OSError, TypeError, ValueError) as error:
        print(f"Environment configuration error: {error}", file=sys.stderr)
        sys.exit(1)
