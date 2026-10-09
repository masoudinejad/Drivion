"""Resolve the central configuration's named Python environment."""

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


if __name__ == "__main__":
    import sys

    try:
        print(environment_path(sys.argv[1]))
    except (KeyError, OSError, ValueError) as error:
        print(f"Environment configuration error: {error}", file=sys.stderr)
        sys.exit(1)
