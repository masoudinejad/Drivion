"""Evaluate the configured runtime as its owner, returning one JSON report.

The boot collector launches this worker with dropped privileges before executing
anything in the user-managed environment. Standard output is reserved for JSON.
"""

import contextlib
import json
import platform
import sys

import tomllib
from pathlib import Path


def evaluate(car_root):
    """Collect independent failures without skipping the remaining evaluations."""
    root = Path(car_root).resolve()
    sys.path.insert(0, str(root.parent))
    from ..environment import environment_path

    results = {}
    config = None
    try:
        from car.src.config import load_config

        config = load_config(root / "config.toml")
        results["configuration"] = {"status": "ok"}
    except (
        ImportError,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
        KeyError,
    ) as error:
        results["configuration"] = {"status": "error", "error": str(error)}

    environment = {
        "status": "ok",
        "python_version": platform.python_version(),
        "executable": sys.executable,
        "path": sys.prefix,
    }
    try:
        if Path(sys.prefix).resolve() != environment_path(root):
            raise ValueError("Not running in the configured Python environment")
        from packaging.specifiers import SpecifierSet
        from ..verify_environment import dependency_report

        with (root / "system/pyproject.toml").open("rb") as source:
            required_python = tomllib.load(source)["project"]["requires-python"]
        environment["required_python"] = required_python
        python_matches = SpecifierSet(required_python).contains(
            platform.python_version()
        )
        if not python_matches:
            environment.update(
                status="error", error=f"Python does not satisfy {required_python}"
            )
        environment["dependencies"] = dependency_report(root)
        if any(item["status"] != "ok" for item in environment["dependencies"]):
            environment["status"] = "error"
    except (
        ImportError,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
        KeyError,
    ) as error:
        environment.update(status="error", error=str(error))
    results["environment"] = environment

    try:
        # Import Picamera2 directly: inventory does not need application NumPy or
        # configuration, and must still work when another runtime check fails.
        from picamera2 import Picamera2

        devices = [
            {
                "id": info["Id"],
                "model": info.get("Model", "unknown"),
                "index": index,
                **{
                    key.lower(): info[key]
                    for key in ("Location", "Rotation")
                    if key in info
                },
            }
            for index, info in enumerate(Picamera2.global_camera_info())
        ]
        results["camera"] = {
            "status": "ok" if devices else "missing",
            "devices": devices,
            "id_kind": "connection",
        }
    except (
        ImportError,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
        KeyError,
    ) as error:
        results["camera"] = {"status": "error", "error": str(error), "devices": []}
    try:
        from car.src.joystick.discovery import discover, resolve_controller

        controllers, errors = discover()
        joystick = {
            "status": "ok",
            "devices": [
                {**device.identity.model_dump(), "path": device.path}
                for device in controllers
            ],
            "errors": errors,
        }
        if config is None:
            joystick.update(status="error", error="Configuration validation failed")
        elif not config.joystick.name:
            joystick["status"] = "unconfigured"
        else:
            joystick["selected"] = config.joystick.name
            try:
                joystick["address"] = resolve_controller(
                    controllers, config.joystick
                ).path
            except RuntimeError as error:
                joystick.update(status="missing", error=str(error))
        if errors and joystick["status"] == "ok":
            joystick["status"] = "warning"
        results["joystick"] = joystick
    except (
        ImportError,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
        KeyError,
    ) as error:
        results["joystick"] = {"status": "error", "error": str(error), "devices": []}
    return results


def main():
    with contextlib.redirect_stdout(sys.stderr):
        result = evaluate(sys.argv[1])
    print(json.dumps(result))


if __name__ == "__main__":
    main()
