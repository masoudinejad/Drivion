"""Validate TOML settings and programmatic camera overrides without hardware."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from car.src.config import AppConfig, load_config, update_config

REPOSITORY_CONFIG = Path(__file__).parents[3] / "car/config.toml"


def camera_config(**overrides):
    """Use central TOML as the only source of camera defaults."""
    return load_config().camera.with_overrides(**overrides)


def test_repository_config_loads():
    config = load_config()
    assert config.camera.frame_rate == 41.0
    assert (config.camera.sensor_width, config.camera.sensor_height) == (1640, 1232)
    assert config.camera.file_format == "numpy"
    assert config.system.python_environment.name == "drivion"
    assert config.system.network.fallback_ipv4_address == "10.42.0.1"
    assert config.system.network.fallback_delay_seconds == 60
    assert config.arduino.address == "auto"
    assert config.arduino.sketchbook_directory == "system/arduino/code"
    assert config.camera.jpeg_quality == 95
    assert config.camera.buffer_count == 4


def test_update_config_preserves_comments_and_permissions(tmp_path):
    path = tmp_path / "config.toml"
    original = REPOSITORY_CONFIG.read_text()
    path.write_text(original)
    path.chmod(0o640)
    config = update_config("camera.frame_rate", 30.0, path)
    assert config.camera.frame_rate == 30.0
    assert load_config(path) == config
    assert "frame_rate = 30.0 # Frames per second" in path.read_text()
    assert "frame_rate = 41.0 # Frames per second" in original
    assert path.stat().st_mode & 0o777 == 0o640


@pytest.mark.parametrize(
    "parameter,value,error",
    [
        ("camera.frame_rate", -1.0, ValidationError),
        ("camera.frame_rate", "30", ValidationError),
        ("camera.framerate", 30.0, KeyError),
        ("camera", {}, KeyError),
        ("camera.frame_rate.value", 30.0, KeyError),
        ("", 30.0, KeyError),
    ],
)
def test_update_config_rejects_changes_without_writing(
    tmp_path, parameter, value, error
):
    path = tmp_path / "config.toml"
    original = REPOSITORY_CONFIG.read_bytes()
    path.write_bytes(original)
    with pytest.raises(error):
        update_config(parameter, value, path)
    assert path.read_bytes() == original


def test_update_config_validates_related_settings(tmp_path):
    path = tmp_path / "config.toml"
    original = REPOSITORY_CONFIG.read_bytes()
    path.write_bytes(original)
    with pytest.raises(ValidationError):
        update_config("system.network.fallback_timer_accuracy_seconds", 61, path)
    assert path.read_bytes() == original


def test_update_config_failed_replace_leaves_original(tmp_path, monkeypatch):
    path = tmp_path / "config.toml"
    original = REPOSITORY_CONFIG.read_bytes()
    path.write_bytes(original)

    def fail_replace(*args):
        raise OSError("Replacement failed")

    monkeypatch.setattr("car.src.config.os.replace", fail_replace)
    with pytest.raises(OSError, match="Replacement failed"):
        update_config("camera.frame_rate", 30.0, path)
    assert path.read_bytes() == original
    assert list(tmp_path.iterdir()) == [path]


def test_override_preserves_other_fields_and_original():
    camera = camera_config(width=640, height=480, channels="y")
    changed = camera.with_overrides(frame_rate=60.0)
    assert changed.frame_rate == 60.0
    assert changed.width == 640
    assert changed.channels == "y"
    assert camera.frame_rate == 41.0
    with pytest.raises(ValidationError):
        changed.width = 800


def test_root_override_revalidates_section():
    config = load_config()
    changed = config.with_overrides(
        camera=config.camera.with_overrides(frame_rate=30.0)
    )
    assert changed.camera.frame_rate == 30.0
    assert config.camera.frame_rate == 41.0
    with pytest.raises(ValidationError):
        config.with_overrides(camera={"frame_rate": -1.0})


@pytest.mark.parametrize(
    "overrides",
    [
        {"width": 0},
        {"height": 123},
        {"width": "640"},
        {"frame_rate": "60"},
        {"frame_rate": "max"},
        {"sensor_mode": "fastest_full_fov"},
        {"sensor_width": 0},
        {"sensor_height": "1232"},
        {"sensor_bit_depth": 10},
        {"frame_rate": 0},
        {"frame_rate": float("inf")},
        {"frame_rate": float("nan")},
        {"channels": "bgr"},
        {"file_format": "png"},
        {"auto_exposure": True},
        {"camera_index": 0},
        {"exposure_time_us": 1000},
        {"auto_exposure": False},
        {"horizontal_flip": False},
        {"vertical_flip": False},
        {"framerate": 60.0},
    ],
)
def test_invalid_overrides_rejected(overrides):
    with pytest.raises(ValidationError):
        camera_config().with_overrides(**overrides)


def test_integer_frame_rate():
    config = camera_config().with_overrides(frame_rate=30)
    assert config.frame_rate == 30.0


def test_toml_error_identifies_setting(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        REPOSITORY_CONFIG.read_text().replace("frame_rate = 41.0", 'frame_rate = "60"')
    )
    with pytest.raises(ValidationError) as error:
        load_config(path)
    assert all(
        item["loc"][:2] == ("camera", "frame_rate") for item in error.value.errors()
    )


def test_unknown_sections_and_unimplemented_settings_rejected():
    values = load_config().model_dump()
    values["camrea"] = {}
    with pytest.raises(ValidationError):
        AppConfig.model_validate(values)
    values = load_config().model_dump()
    values["recording"] = {"unknown": True}
    with pytest.raises(ValidationError):
        AppConfig.model_validate(values)


@pytest.mark.parametrize(
    "field,value",
    [
        ("fallback_ipv4_address", "10.42.0.0"),
        ("fallback_ssid_prefix", "x" * 26),
        ("fallback_timer_accuracy_seconds", 61),
    ],
)
def test_invalid_network_settings_rejected(field, value):
    values = load_config().model_dump()
    values["system"]["network"][field] = value
    with pytest.raises(ValidationError):
        AppConfig.model_validate(values)


@pytest.mark.parametrize(
    "field,value",
    [
        ("address", "bad\naddress"),
        ("sketchbook_directory", "../outside"),
        ("sketchbook_directory", "/absolute/path"),
    ],
)
def test_invalid_arduino_settings_rejected(field, value):
    values = load_config().model_dump()
    values["arduino"][field] = value
    with pytest.raises(ValidationError):
        AppConfig.model_validate(values)


@pytest.mark.parametrize("channels", ["rgb", "y"])
def test_jpeg_override_preserves_channel_selection(channels):
    original = camera_config(channels=channels)
    changed = original.with_overrides(file_format="jpeg")
    assert changed.file_format == "jpeg"
    assert changed.channels == channels
    assert original.file_format == "numpy"
