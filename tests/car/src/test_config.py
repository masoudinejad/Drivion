"""Validate TOML settings and programmatic camera overrides without hardware."""

import pytest
from pydantic import ValidationError

from car.src.camera.config import CameraConfig
from car.src.config import AppConfig, load_config


def test_repository_config_loads():
    config = load_config()
    assert config.camera.frame_rate == 41.0
    assert (config.camera.sensor_width, config.camera.sensor_height) == (1640, 1232)
    assert config.camera.file_format == "numpy"
    assert config.system.python_environment.name == "drivion"
    assert config.system.network.fallback_ipv4_address == "10.42.0.1"
    assert config.system.network.fallback_delay_seconds == 60
    assert config.system.provisioning.uv.version == "0.12.20"
    assert config.system.provisioning.uv.executable_directory == "/usr/local/bin"
    assert config.arduino.provisioning is not None
    assert len(config.arduino.provisioning.cli_archive_sha256) == 64


def test_override_preserves_other_fields_and_original():
    camera = CameraConfig(width=640, height=480, channels="y")
    changed = camera.with_overrides(frame_rate=60.0)
    assert changed.frame_rate == 60.0
    assert changed.width == 640
    assert changed.channels == "y"
    assert camera.frame_rate == 41.0
    with pytest.raises(ValidationError):
        changed.width = 800


def test_root_override_revalidates_section():
    config = AppConfig()
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
        CameraConfig().with_overrides(**overrides)


def test_integer_frame_rate():
    config = CameraConfig().with_overrides(frame_rate=30)
    assert config.frame_rate == 30.0


def test_toml_error_identifies_setting(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[camera]\nframe_rate="60"\n')
    with pytest.raises(ValidationError) as error:
        load_config(path)
    assert all(
        item["loc"][:2] == ("camera", "frame_rate") for item in error.value.errors()
    )


def test_unknown_sections_and_unimplemented_settings_rejected():
    with pytest.raises(ValidationError):
        AppConfig.model_validate({"camrea": {}})
    with pytest.raises(ValidationError):
        AppConfig.model_validate({"recording": {"unknown": True}})


@pytest.mark.parametrize(
    "field,value",
    [
        ("fallback_ipv4_address", "10.42.0.0"),
        ("fallback_ssid_prefix", "x" * 26),
        ("fallback_timer_accuracy_seconds", 61),
    ],
)
def test_invalid_network_settings_rejected(field, value):
    system = load_config().system.model_dump()
    system["network"][field] = value
    with pytest.raises(ValidationError):
        AppConfig.model_validate({"system": system})


@pytest.mark.parametrize(
    "field,value",
    [
        ("data_directory", "/home/driver/.arduino15"),
        ("download_directory", "../staging"),
        ("config_path", ".arduino15/nested/arduino-cli.yaml"),
        ("sketchbook_directory", "../outside"),
        ("cli_install_directory", "opt/arduino-cli"),
    ],
)
def test_invalid_arduino_provisioning_paths_rejected(field, value):
    config = load_config().arduino.provisioning.model_dump()
    config[field] = value
    with pytest.raises(ValidationError):
        AppConfig.model_validate({"arduino": {"provisioning": config}})


@pytest.mark.parametrize("channels", ["rgb", "y"])
def test_jpeg_override_preserves_channel_selection(channels):
    original = CameraConfig(channels=channels)
    changed = original.with_overrides(file_format="jpeg")
    assert changed.file_format == "jpeg"
    assert changed.channels == channels
    assert original.file_format == "numpy"
