"""Read and present generated system information without probing hardware."""

from pathlib import Path

import tomllib

from ..ui.navigation import show_page
from .update import INFO_PATH


def load_info(car_root):
    """Read the latest generated TOML, leaving it unchanged."""
    path = Path(car_root) / INFO_PATH
    with path.open("rb") as source:
        return tomllib.load(source)


def _safe_text(value):
    """Prevent persisted information from injecting terminal control sequences."""
    return "".join(
        character if character.isprintable() else " " for character in str(value)
    )


def render_info(info):
    """Render every field, including future sections, in TOML source order."""
    lines = []

    def render_table(table, prefix=""):
        fields = {
            key: value for key, value in table.items() if not isinstance(value, dict)
        }
        if fields:
            lines.append(_safe_text(prefix.replace("_", " ").title() or "Information"))
            labels = {
                key: _safe_text(key.replace("_", " ").capitalize()) for key in fields
            }
            width = max(map(len, labels.values()))
            for key, value in fields.items():
                if isinstance(value, bool):
                    value = "Yes" if value else "No"
                lines.append(f"  {labels[key]:<{width}} : {_safe_text(value)}")
            lines.append("")
        for key, value in table.items():
            if isinstance(value, dict):
                render_table(value, f"{prefix} / {key}" if prefix else key)

    render_table(info)
    return "\n".join(lines).rstrip() or "No system information is available yet."


def system_info_page(car_root):
    """Reload and show software, hardware, system, and network information."""
    show_page("System Info", render_info(load_info(car_root)))
