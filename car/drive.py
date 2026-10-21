#!/usr/bin/env python3
"""Start the car using the Python environment selected in config.toml."""

import sys
from pathlib import Path

from system.environment import enter_environment
from system.ui.startup import show_startup


def main():
    # Dependencies are available only after enter_environment has re-executed us.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from car.src.config import load_config

    load_config(Path(__file__).resolve().parent / "config.toml")
    show_startup()


if __name__ == "__main__":
    try:
        enter_environment(Path(__file__).resolve().parent, __file__)
        main()
    except (OSError, TypeError, ValueError) as error:
        print(f"Drivion startup error: {error}", file=sys.stderr)
        sys.exit(1)
