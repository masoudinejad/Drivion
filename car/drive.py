#!/usr/bin/python3
"""Start the car using the Python environment selected in config.toml."""

import os
import sys
from pathlib import Path

from system.environment import environment_path


def enter_environment():
    root = Path(__file__).resolve().parent
    target = environment_path(root)
    # Compare prefixes rather than resolved executable symlinks (both point to
    # system Python). The venv prefix distinguishes the configured environment.
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
        [str(python), str(Path(__file__).resolve()), *sys.argv[1:]],
        environment,
    )


def main():
    print("Drivion structure is ready. Driving functionality is not implemented yet.")


if __name__ == "__main__":
    try:
        enter_environment()
        main()
    except (OSError, ValueError) as error:
        print(f"Drivion startup error: {error}", file=sys.stderr)
        sys.exit(1)
