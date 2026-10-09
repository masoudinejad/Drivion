"""Firmware requirements belong to the sketch; config supplies values only."""

import copy
from pathlib import Path

import pytest
import tomllib

from car.system.arduino.firmware.definitions import (
    load_firmware,
    resolve_firmware,
    validate_parameter_values,
)

ROOT = Path(__file__).resolve().parents[3] / "car"
DEFINITION = {
    "firmware": {
        "version": "1.0.0",
        "protocol_version": 1,
        "fqbn": "arduino:avr:nano:cpu=atmega328",
    },
    "parameters": {
        "BLINK_DURATION_MS": {"type": "integer", "minimum": 1, "maximum": 4294967295}
    },
}


def test_central_configuration_contains_values_not_requirements():
    with (ROOT / "config.toml").open("rb") as stream:
        config = tomllib.load(stream)
    assert config["firmware"]["board_setup_test"] == {"BLINK_DURATION_MS": 500}
    assert "firmware_compile" not in config
    assert "firmware_flash" not in config
    resolved = load_firmware("board_setup_test", ROOT)
    assert resolved["version"] == "1.0.0"
    assert resolved["parameters"] == config["firmware"]["board_setup_test"]


@pytest.mark.parametrize(
    "values",
    [
        {},
        {"BLINK_DURATION_MS": 500, "EXTRA": 1},
        {"BLINK_DURATION_MS": 0},
        {"BLINK_DURATION_MS": -1},
        {"BLINK_DURATION_MS": 0.5},
        {"BLINK_DURATION_MS": True},
        {"BLINK_DURATION_MS": "500"},
        {"BLINK_DURATION_MS": 2**32},
    ],
)
def test_missing_extra_wrong_type_and_invalid_range_rejected(values):
    with pytest.raises(ValueError):
        resolve_firmware(DEFINITION, values)


def test_definition_cannot_hide_fallback_defaults():
    definition = copy.deepcopy(DEFINITION)
    definition["parameters"]["BLINK_DURATION_MS"]["default"] = 500
    with pytest.raises(ValueError, match="declaration"):
        resolve_firmware(definition, {"BLINK_DURATION_MS": 500})


def test_user_config_rejects_metadata_and_old_nested_structure():
    for entry in ({"version": "1.0.0"}, {"parameters": {"BLINK_DURATION_MS": 500}}):
        with pytest.raises(ValueError):
            validate_parameter_values({"board_setup_test": entry})
