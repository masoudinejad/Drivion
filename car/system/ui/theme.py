"""Load the shared TOML terminal palette for Python and Bash callers."""

import sys
from pathlib import Path

import tomllib

STYLE_NAMES = ("cyan", "amber", "red", "green", "gray", "bold", "dim", "reset")


def load_theme(styled=True):
    """Return ANSI styles, or empty strings when styling is disabled."""
    with Path(__file__).with_suffix(".toml").open("rb") as source:
        styles = tomllib.load(source)["styles"]
    for name in STYLE_NAMES:
        code = styles[name]
        if type(code) is not int or not 0 <= code <= 107:
            raise ValueError(f"Invalid ANSI style: {name}")
    return {name: f"\033[{styles[name]}m" if styled else "" for name in STYLE_NAMES}


if __name__ == "__main__":
    # Only validated numeric codes cross the Python/Bash boundary.
    theme = load_theme()
    sys.stdout.write(" ".join(theme[name][2:-1] for name in STYLE_NAMES) + "\n")
