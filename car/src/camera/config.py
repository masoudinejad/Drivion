"""Camera settings independent of Picamera2 and connected hardware."""

from typing import Annotated, Literal

from pydantic import Field

from car.src.configuration.base import ConfigModel

PositiveRate = Annotated[float, Field(gt=0, allow_inf_nan=False)]


class CameraConfig(ConfigModel):
    """Requested capture settings, not a guarantee of hardware throughput.

    Sensor dimensions and frame rate are explicitly configured. Sensor bit depth
    uses the system default; capture always enables automatic exposure.
    Hardware discovery is separate from configuration loading. Output resizing
    must preserve all sensor content (use padding for a different aspect ratio),
    rather than crop the field of view.
    RGB output is an H x W x 3 uint8 array in RGB order; Y is H x W uint8
    luminance extracted from YUV. Files use .npy for NumPy or .jpg for JPEG.
    """

    width: int = Field(default=640, gt=0, multiple_of=2)
    height: int = Field(default=480, gt=0, multiple_of=2)
    channels: Literal["rgb", "y"] = "rgb"
    file_format: Literal["numpy", "jpeg"] = "numpy"
    sensor_width: int = Field(default=1640, gt=0, multiple_of=2)
    sensor_height: int = Field(default=1232, gt=0, multiple_of=2)
    frame_rate: PositiveRate = 41.0
