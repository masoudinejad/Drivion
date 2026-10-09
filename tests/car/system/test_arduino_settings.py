"""Reject recursive directory layouts and reuse operation configuration reads."""

from pathlib import Path
from unittest.mock import patch

import pytest
import tomlkit
import tomllib

from car.system.arduino.firmware.definitions import load_firmware
from car.system.arduino.settings import (
    load_context,
    tool_settings,
    validate_compile_configuration,
)


@pytest.mark.parametrize(
    "library",
    [
        "system/arduino/build",
        "system/arduino/build/shared",
        "system/arduino",
    ],
)
def test_library_cannot_contain_or_be_inside_builds(car_tree, library):
    settings = {**tool_settings(car_tree, "compile"), "library_directory": library}
    with pytest.raises(ValueError):
        validate_compile_configuration(settings)


@pytest.mark.parametrize(
    "key,value",
    [
        ("build_directory", "system/arduino/library/nested"),
        ("log_directory", "system/arduino/sketches/logs"),
        ("log_directory", "system/arduino/library"),
    ],
)
def test_complete_layout_rejects_output_source_overlap(car_tree, key, value):
    path = car_tree / "system/pyproject.toml"
    document = tomlkit.parse(path.read_text())
    kind = "firmware_flash" if key == "log_directory" else "firmware_compile"
    document["tool"]["drivion"][kind][key] = value
    path.write_text(tomlkit.dumps(document))
    with pytest.raises(ValueError, match="overlap"):
        load_context(car_tree)


def test_resolved_symlink_overlap_is_rejected(car_tree):
    (car_tree / "system/arduino/build").symlink_to(
        car_tree / "system/arduino/library", target_is_directory=True
    )
    with pytest.raises(ValueError, match="overlap"):
        load_context(car_tree)


def test_workflow_context_reads_central_toml_only_once(car_tree):
    original = tomllib.load
    paths = []

    def read(stream):
        paths.append(Path(stream.name))
        return original(stream)

    with patch("car.system.arduino.settings.tomllib.load", side_effect=read):
        context = load_context(car_tree)
        for _ in range(2):
            load_firmware("board_setup_test", car_tree, context=context)
    assert paths.count(car_tree / "config.toml") == 1
    assert paths.count(car_tree / "system/pyproject.toml") == 1
