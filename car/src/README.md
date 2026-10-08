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
from car.src.camera.camera import Camera

config = load_config()
camera_config = config.camera.with_overrides(
    channels="y",
    frame_rate=30.0,
)
with Camera(camera_config) as camera:
    frame = camera.single_capture()
    camera.save_capture("test_frame")

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

## Camera capture

`Camera(config.camera)` configures and starts the default camera without a preview.
It applies the sensor dimensions directly, leaving bit depth at the system default.
It checks the applied sensor/stream dimensions and the frame-duration limits,
rejecting unsupported settings instead of silently substituting a different mode.
It does not enumerate modes or choose a frame rate automatically.

The ISP scales the configured sensor view to fit the output dimensions. Frames
with a different aspect ratio receive black padding; all sensor content is kept.
Even stream dimensions can introduce a small aspect-ratio rounding error.
RGB capture uses Picamera2's `BGR888` format, which yields RGB arrays in memory.
Y capture extracts only luminance, excluding chroma and row padding.
Each returned frame owns its memory. `current_img` refers to the latest returned
frame, and `capture_count` counts successful captures.

Automatic exposure is enabled with equal minimum and maximum frame durations.
Four buffers are used internally, with cached-frame queuing disabled. Capture
waits for a completed frame, without promising when its exposure began.
Use a context manager or `close()` to release the device. Camera operations are
not thread-safe. Application logging settings are left unchanged.

`save_capture(path)` captures and saves synchronously in the configured format.
`save_frame(frame, path, config)` saves an existing frame. Missing extensions are
supplied; conflicting extensions are rejected. Parent folders must already exist.
JPEG uses quality 95. Continuous recording should manage its own saving queue.

Run the benchmark from the repository root in the car's Python environment:

```sh
python -m car.src.camera.fast_cam_test --seconds 10
python -m car.src.camera.fast_cam_test --channels y --save-frames captures
python -m car.src.camera.fast_cam_test --format jpeg --save test_frame
```

The benchmark loads TOML and applies only explicitly supplied CLI overrides.
Optional saving is synchronous and included in measured throughput. Hardware
sensor FPS, actual exposure timing and full FOV must be verified on the Pi;
benchmark loop throughput alone does not establish those properties.

Reference: [Picamera2 manual](https://datasheets.raspberrypi.com/camera/picamera2-manual.pdf).
