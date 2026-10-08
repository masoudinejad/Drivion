# Driving application modules

Python modules for configuration, camera capture, joystick input, Arduino
communication, drive control, inference, and recording. All modules share the
environment managed in `../system/`.

## Configuration

`config.py` loads the central `car/config.toml` into a Pydantic `AppConfig`.
Models reject unknown keys, invalid types and invalid values. Missing application
sections use model defaults; a supplied system section requires its existing
Python environment fields. Empty sections reserve future schemas and reject settings
until their models are defined. System provisioning tools keep their existing
loaders so they can run before application dependencies are installed.

Pass each component its own section. Use `with_overrides` to create a validated
copy while retaining other settings and leaving the original unchanged:

```python
from car.src.config import load_config

config = load_config()
camera_config = config.camera.with_overrides(
    channels="y",
    frame_rate=30.0,
)
# When the capture class is implemented: Camera(camera_config)

# Revalidate the root when a change affects multiple sections:
config = config.with_overrides(camera=camera_config)
```

Overrides replace fields; nested dictionaries replace whole sections. Call the
section's `with_overrides` first to retain its other settings. Avoid Pydantic's
`model_copy(update=...)`, which bypasses update validation.

### Camera settings

- `width` and `height`: positive even output dimensions (compatible with YUV420).
  Defaults are 640 × 480; output dimensions are separate from sensor resolution.
- `channels`: `"rgb"` for an H × W × 3 RGB array, or `"y"` for an H × W
  luminance array. Both use uint8 values.
- `file_format`: `"numpy"` (default) for lossless `.npy` arrays, or `"jpeg"` for
  lossy `.jpg` images. JPEG with `channels="y"` saves a grayscale image.
- `sensor_width`, `sensor_height`: explicit sensor dimensions. Defaults are
  1640 × 1232 for Camera v2 full FOV. Sensor bit depth uses the system default.
  Hardware discovery tools can supply other values; loading config does no discovery.
- `frame_rate`: a positive finite numeric rate, defaulting to 41 FPS.
  The capture implementation will apply these explicit settings.

Capture always enables automatic exposure. Exposure, sensor bit depth, device
index and orientation are not configurable. The initial camera implementation
will use the default camera and its default orientation. New configuration
fields can be added when a concrete requirement arises.

This stage implements configuration and validation only. Applying sensor settings,
capture, RGB/Y extraction, padding and NumPy/JPEG saving will be implemented
in the camera
module. Advertised sensor FPS is not a guarantee of end-to-end processing speed.

Reference: [Picamera2 manual](https://datasheets.raspberrypi.com/camera/picamera2-manual.pdf).
