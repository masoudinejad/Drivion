"""Shared isolated car tree for Arduino operation tests."""

import shutil
from pathlib import Path

import pytest


@pytest.fixture
def car_tree(tmp_path):
    """Copy central settings and firmware sources without generated outputs."""
    source = Path(__file__).resolve().parents[3] / "car"
    root = tmp_path / "car"
    root.mkdir()
    shutil.copy(source / "config.toml", root)
    (root / "system").mkdir()
    shutil.copy(source / "system/pyproject.toml", root / "system")
    for name in ("library", "sketches"):
        shutil.copytree(
            source / "system/arduino" / name, root / "system/arduino" / name
        )
    return root
