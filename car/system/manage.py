#!/usr/bin/env python3
"""Open the central setup, settings, and administration menu."""

import sys
from pathlib import Path

# Support execution by absolute path from any working directory.
CAR_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CAR_ROOT.parent))
sys.path.insert(0, str(CAR_ROOT))

from system.environment import enter_environment
from system.management.application import run_management
from system.ui.screen import terminal_screen


def main():
    """Enter the configured environment and open the central management menu."""
    try:
        enter_environment(CAR_ROOT, __file__)
        with terminal_screen():
            run_management(CAR_ROOT)
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError, RuntimeError) as error:
        print(f"System management error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
