"""Headless capture using the central camera configuration."""

from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Self

import numpy as np

from car.src.camera.config import CameraConfig

logger = logging.getLogger(__name__)


def _create_camera():
    # Keep configuration, saving and tests usable on machines without libcamera.
    from picamera2 import Picamera2

    return Picamera2()


def save_frame(frame: np.ndarray, path: str | Path, config: CameraConfig) -> Path:
    """Save an RGB or Y frame in the configured format and return its path.

    A missing suffix is supplied. A conflicting suffix is rejected so file
    contents cannot silently disagree with their extension. Parent directories
    must already exist. Saving is synchronous; callers manage recording queues.
    """
    path = Path(path)
    extension = ".npy" if config.file_format == "numpy" else ".jpg"
    allowed = {".npy"} if config.file_format == "numpy" else {".jpg", ".jpeg"}
    if not path.suffix:
        path = path.with_suffix(extension)
    elif path.suffix.lower() not in allowed:
        raise ValueError(
            f"File suffix {path.suffix!r} conflicts with {config.file_format}"
        )
    shape = (config.height, config.width)
    if config.channels == "rgb":
        shape += (3,)
    if frame.shape != shape or frame.dtype != np.uint8:
        raise ValueError(
            f"Expected uint8 frame with shape {shape}, got {frame.shape}/{frame.dtype}"
        )
    if config.file_format == "numpy":
        with path.open("wb") as stream:
            np.save(stream, frame, allow_pickle=False)
    else:
        from PIL import Image

        Image.fromarray(frame).save(path, format="JPEG", quality=95)
    return path


class Camera:
    """Configure and start the default camera, then capture RGB or luminance.

    Sensor resolution and FPS are taken directly from CameraConfig; there is no
    sensor-mode discovery or rate selection. Automatic exposure is always on,
    with a fixed frame period. Sensor bit depth is left to Picamera2 defaults.

    The ISP scales the entire configured sensor view to fit inside the requested
    output dimensions. Different aspect ratios receive black padding, not a crop.
    The sensor and stream sizes applied by libcamera must match the request.

    Four buffers are used internally. queue=False avoids repeatedly returning
    Picamera2's cached latest frame in a tight capture loop. Capture waits for a
    completed frame; it does not guarantee that exposure began after the call.
    Use a context manager or close() to release the device. Not thread-safe.
    """

    def __init__(self, config: CameraConfig) -> None:
        if not isinstance(config, CameraConfig):
            raise TypeError("config must be a CameraConfig")
        self.config = CameraConfig.model_validate(config)
        self.camera = None
        self.capture_count = 0
        self.current_img: np.ndarray | None = None
        self.output_size = (config.width, config.height)
        self._started = False
        self.camera = _create_camera()
        try:
            self._configure()
            self.camera.start(show_preview=False)
            self._started = True
        except Exception:
            try:
                self.close()
            except Exception:
                logger.exception("Failed to release camera after initialization error")
            raise

    def _configure(self) -> None:
        cfg = self.config
        scale = min(cfg.width / cfg.sensor_width, cfg.height / cfg.sensor_height)
        # Both formats use even dimensions; rounding introduces at most 2 pixels
        # of aspect-ratio error while all sensor content remains visible.
        self._stream_size = (
            min(cfg.width, max(2, round(cfg.sensor_width * scale / 2) * 2)),
            min(cfg.height, max(2, round(cfg.sensor_height * scale / 2) * 2)),
        )
        duration = math.ceil(1_000_000 / cfg.frame_rate)
        self.frame_duration_us = duration
        pixel_format = "BGR888" if cfg.channels == "rgb" else "YUV420"
        capture_config = self.camera.create_video_configuration(
            main={
                "size": self._stream_size,
                "format": pixel_format,
                "preserve_ar": False,
            },
            sensor={"output_size": (cfg.sensor_width, cfg.sensor_height)},
            raw=None,
            controls={"AeEnable": True, "FrameDurationLimits": (duration, duration)},
            buffer_count=4,
            queue=False,
        )
        self.camera.configure(capture_config)
        applied = self.camera.camera_configuration()
        if tuple(applied["sensor"]["output_size"]) != (
            cfg.sensor_width,
            cfg.sensor_height,
        ):
            raise ValueError("Camera cannot apply the configured sensor dimensions")
        if tuple(applied["main"]["size"]) != self._stream_size:
            raise ValueError(
                "Camera cannot apply the configured output stream dimensions"
            )
        if applied["main"]["format"] != pixel_format:
            raise ValueError("Camera cannot apply the configured pixel format")
        minimum, maximum, _ = self.camera.camera_controls["FrameDurationLimits"]
        if not minimum <= duration <= maximum:
            raise ValueError(
                f"Requested {cfg.frame_rate} FPS is outside this sensor mode's "
                f"frame duration limits ({minimum}–{maximum} microseconds)"
            )
        # Reset the crop to the full view of the configured sensor mode. This is
        # not mode discovery: a deliberately cropped sensor mode stays cropped.
        self.camera.set_controls(
            {"ScalerCrop": self.camera.camera_properties["ScalerCropMaximum"]}
        )

    def single_capture(self) -> np.ndarray:
        """Return an independent uint8 array: H×W×3 RGB, or H×W Y."""
        if self.camera is None:
            raise RuntimeError("Camera is closed")
        frame = self.camera.capture_array("main")
        width, height = self._stream_size
        frame = frame[:height, :width]
        left = (self.config.width - width) // 2
        top = (self.config.height - height) // 2
        shape = (self.config.height, self.config.width)
        if self.config.channels == "rgb":
            shape += (3,)
        result = np.zeros(shape, dtype=np.uint8)
        result[top : top + height, left : left + width] = frame
        self.current_img = result
        self.capture_count += 1
        return result

    def save_capture(self, path: str | Path) -> Path:
        """Capture one frame and synchronously save it using file_format."""
        return save_frame(self.single_capture(), path, self.config)

    def close(self) -> None:
        """Release the camera; safe to call repeatedly."""
        camera, self.camera = self.camera, None
        if camera is None:
            return
        try:
            if self._started:
                camera.stop()
        finally:
            self._started = False
            camera.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
