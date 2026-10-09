"""Exercise capture, persistence and device cleanup without Raspberry Pi hardware."""

from copy import deepcopy

import numpy as np
import pytest
from PIL import Image

from car.src.camera import camera as module
from car.src.config import load_config


def camera_config(**overrides):
    """Use central TOML as the only source of camera defaults."""
    return load_config().camera.with_overrides(**overrides)


class FakeCamera:
    def __init__(self):
        self.camera_controls = {"FrameDurationLimits": (23895, 1_000_000, None)}
        self.camera_properties = {"ScalerCropMaximum": (0, 0, 3280, 2464)}
        self.started = self.stopped = self.closed = False
        self.array = None

    def create_video_configuration(self, **kwargs):
        self.requested = deepcopy(kwargs)
        return kwargs

    def configure(self, config):
        self.applied = deepcopy(config)
        width, height = config["main"]["size"]
        if config["main"]["format"] == "YUV420":
            # YUV chroma and row padding must never leak into returned luminance.
            self.array = np.full((height * 3 // 2, width + 8), 200, np.uint8)
            self.array[:height, :width] = 37
        else:
            self.array = np.zeros((height, width, 3), np.uint8)
            self.array[:] = (255, 0, 0)

    def camera_configuration(self):
        return self.applied

    def set_controls(self, values):
        self.controls = values

    def start(self, show_preview):
        assert show_preview is False
        self.started = True

    def capture_array(self, name):
        assert name == "main"
        return self.array

    def stop(self):
        self.stopped = True

    def close(self):
        self.closed = True


@pytest.fixture
def device(monkeypatch):
    fake = FakeCamera()
    monkeypatch.setattr(module, "_create_camera", lambda: fake)
    return fake


def test_explicit_configuration_and_rgb_owned_capture(device):
    config = camera_config()
    with module.Camera(config) as camera:
        assert device.requested["sensor"] == {"output_size": (1640, 1232)}
        assert device.requested["main"]["format"] == "BGR888"
        assert device.requested["main"]["preserve_ar"] is False
        assert device.requested["controls"] == {
            "AeEnable": True,
            "FrameDurationLimits": (24391, 24391),
        }
        assert device.controls["ScalerCrop"] == (0, 0, 3280, 2464)
        frame = camera.single_capture()
        assert frame.shape == (480, 640, 3)
        np.testing.assert_array_equal(frame[10, 10], [255, 0, 0])
        device.array[:] = 0
        assert frame[10, 10, 0] == 255
        assert frame.flags.c_contiguous
        assert camera.capture_count == 1
    assert device.closed and device.stopped
    camera.close()
    with pytest.raises(RuntimeError, match="closed"):
        camera.single_capture()


def test_y_capture_removes_chroma_stride_and_pads_without_cropping(device):
    with module.Camera(camera_config(width=640, height=640, channels="y")) as camera:
        frame = camera.single_capture()
        assert frame.shape == (640, 640)
        width, height = camera._stream_size
        top = (640 - height) // 2
        left = (640 - width) // 2
        assert np.all(frame[top : top + height, left : left + width] == 37)
        assert np.all(frame[:top] == 0)
        assert 200 not in frame
        assert not np.shares_memory(frame, device.array)


def test_configured_sensor_dimensions_are_used(device):
    with module.Camera(camera_config(sensor_width=3280, sensor_height=2464)):
        assert device.requested["sensor"] == {"output_size": (3280, 2464)}


def test_unsupported_fps_releases_device(device):
    with pytest.raises(ValueError, match="frame duration limits"):
        module.Camera(camera_config(frame_rate=60))
    assert device.closed
    assert not device.started


@pytest.mark.parametrize("field", ["sensor", "main"])
def test_adjusted_dimensions_fail_instead_of_silently_changing_settings(device, field):
    configure = device.configure

    def adjusted(config):
        configure(config)
        device.applied[field]["output_size" if field == "sensor" else "size"] = (
            320,
            240,
        )

    device.configure = adjusted
    with pytest.raises(ValueError, match="dimensions"):
        module.Camera(camera_config())
    assert device.closed


def test_start_failure_releases_device_and_keeps_original_error(device):
    def fail(**kwargs):
        raise RuntimeError("start failed")

    device.start = fail
    with pytest.raises(RuntimeError, match="start failed"):
        module.Camera(camera_config())
    assert device.closed


def test_context_closes_device_when_capture_fails(device):
    def fail(name):
        raise RuntimeError("capture failed")

    device.capture_array = fail
    with (
        pytest.raises(RuntimeError, match="capture failed"),
        module.Camera(camera_config()) as camera,
    ):
        camera.single_capture()
    assert device.closed and device.stopped


@pytest.mark.parametrize("channels", ["rgb", "y"])
@pytest.mark.parametrize("file_format", ["numpy", "jpeg"])
def test_save_capture_roundtrip(device, tmp_path, channels, file_format):
    config = camera_config(channels=channels, file_format=file_format)
    with module.Camera(config) as camera:
        path = camera.save_capture(tmp_path / "frame")
        original = camera.current_img
    if file_format == "numpy":
        assert path.suffix == ".npy"
        np.testing.assert_array_equal(np.load(path, allow_pickle=False), original)
    else:
        assert path.suffix == ".jpg"
        with Image.open(path) as image:
            assert image.mode == ("RGB" if channels == "rgb" else "L")
            assert image.size == (640, 480)
            restored = np.asarray(image).astype(int)
            # JPEG chroma subsampling can blur the sharp padding boundary.
            error = np.abs(restored - original.astype(int))
            assert np.mean(error) < 2
            assert np.max(error[16:-16, 16:-16]) <= 5


def test_save_rejects_misleading_suffix_and_wrong_shape(tmp_path):
    config = camera_config()
    frame = np.zeros((480, 640, 3), np.uint8)
    with pytest.raises(ValueError, match="suffix"):
        module.save_frame(frame, tmp_path / "frame.jpg", config)
    with pytest.raises(ValueError, match="shape"):
        module.save_frame(frame[:10], tmp_path / "frame", config)
