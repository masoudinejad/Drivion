#!/usr/bin/env python3
"""Start the car using the Python environment selected in config.toml."""

import sys
from pathlib import Path

from system.environment import enter_environment
from system.ui.startup import show_startup
from system.ui.progress import run_background


def main():
    # Dependencies are available only after enter_environment has re-executed us.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from system.information.update import refresh_info

    root = Path(__file__).resolve().parent
    report = run_background("Evaluating hardware and software", refresh_info, root)
    show_startup(report)
    failed = [
        name
        for name in ("configuration", "environment")
        if report[name]["status"] != "ok"
    ]
    if failed:
        raise ValueError(
            "Central startup evaluation failed: "
            + ", ".join(failed)
            + "; see system/info.toml"
        )


if __name__ == "__main__":
    try:
        try:
            enter_environment(Path(__file__).resolve().parent, __file__)
        except (OSError, TypeError, ValueError):
            # Bootstrap failures must also reach the central snapshot, even
            # when the configured environment cannot execute the launcher.
            main()
            raise
        main()
    except (OSError, TypeError, ValueError) as error:
        print(f"Drivion startup error: {error}", file=sys.stderr)
        sys.exit(1)
