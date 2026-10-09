"""Dispatch management features independently of their terminal presentation."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ..information.view import system_info_page
from ..ui.navigation import select_item, show_page


@dataclass(frozen=True)
class MenuItem:
    """A category label and its action, receiving the deployed car root."""

    label: str
    action: Callable[[Path], None]


def default_items():
    """Register implemented categories; add future setup/settings/admin here."""
    return (MenuItem("System Info", system_info_page),)


def run_management(car_root, *, items=None, select=select_item, display=show_page):
    """Run actions until Back, recovering from readable feature errors."""
    root = Path(car_root).resolve()
    items = tuple(default_items() if items is None else items)
    while True:
        selected = select("Drivion system management", [item.label for item in items])
        if selected is None:
            return
        if not 0 <= selected < len(items):
            raise ValueError("Invalid management menu selection")
        item = items[selected]
        try:
            item.action(root)
        except (OSError, ValueError, RuntimeError) as error:
            display(f"{item.label} unavailable", str(error))
