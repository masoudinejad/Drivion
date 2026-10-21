# Joystick input

## Identification

In system management, choose **Joystick → Identify and select device**.
Selection saves the readable `name`, `vendor`, `product`, and `unique_id` in
`car/config.toml`. Back leaves settings intact. Discovery captures button and
axis specifications internally without printing detail pages.

Matching ignores event numbers and physical paths, including after reboot or
USB port changes. A unique ID distinguishes individual controllers when the
hardware provides one. Otherwise exactly one controller with the saved name and
vendor/product must be connected; identical units cannot be distinguished.
Selecting a different controller clears axis calibration but retains response
preferences. Selecting the same controller preserves its calibration.

Linux `evdev` is already included in the car environment. The Pi user needs
read access to the controller under `/dev/input`. Devices must expose joystick
or gamepad buttons and absolute axes. Failed discovery shows diagnostics.

## Control setup

Choose **Joystick → Configure controls**. Initialization shows the shared waiting
animation and a success status. The first prompt reminds you to wake an idle
wireless controller, check the connection, and release both sticks. If an endpoint
has no useful movement, retry messages also suggest waking the controller.
Unchanged axis values alone do not establish whether a wireless controller is
asleep, disconnected from its receiver, or simply held still.
Press Enter on **Capture reading** while holding the requested position; no
boolean answer needs typing. Back/Escape cancels. Release both sticks for the
steering neutral sample, then hold right stick left and right. Release both
sticks again for a fresh speed neutral sample, then hold left stick down and up.

Detection locks the dominant axis at the first endpoint, then reads only that
axis when validating the opposite endpoint. Small perpendicular movement is fine.
Speed detection excludes the assigned steering axis. If an endpoint is invalid,
its prompt repeats with an explanation while earlier valid samples stay in
memory. Steering calibration stays intact while retrying speed. First endpoints
that are too diagonal or have insufficient travel are retried as well. Device
I/O failures still abort; the configuration remains unchanged.

Choose the two response modes independently, enable or disable reverse, and enter
one neutral dead zone as a fraction (for example `0.05` means 5% of each side's
travel). Invalid dead-zone values repeat only that setting; calibration and
response choices are kept. A live preview then uses the pending settings:
accurate controls show gauges and decimal values, fixed controls show direction
states, and forward-only speed uses a one-sided gauge. Move each stick to check
the result; Enter
continues only after both controls have changed. Escape cancels without saving.
A lack of recent control changes shows a wake-up/connection hint. The preview
reads input only and sends no drive commands. Review the choices before accepting
the final save prompt. Back, Ignore, or leaving the save prompt leaves the
configuration untouched. Configuration updates are atomic. Setup does not send
commands to the Arduino or move the car.

`[joystick.controls]` contains only interpretation settings:

- `allow_reverse`: when false, backward stick input produces zero speed.
- `speed_mode`, `steering_mode`: independently `"accurate"` or `"fixed"`.
- `dead_zone`: fraction in `[0, 1)` treated as neutral.
- `speed`, `steering`: calibration tables saved by setup, each containing `axis`,
  `minimum`, `centre`, `maximum`, and `inverted`.

| Input | Accurate mode | Fixed mode |
| --- | --- | --- |
| Right stick left/right | Any steering value from -1 to +1 | -1 / +1 |
| Left stick down/up | Any speed value from -1 to +1 | -1 / +1 |
| Either stick inside dead zone | 0 | 0 |

Up means forward (+), down means backward (-); right steering is positive.
Each side is normalized independently around the calibrated centre, clamped to
its limit, and rescaled outside the dead zone to retain full travel. Fixed speed
is a unit demand for a single driving speed; the drive layer chooses the actual
speed. Physical speed and steering-angle limits belong to that layer.

Setup's excursion, dominance, preview refresh, and inactivity thresholds live in
`system/pyproject.toml`, under `tool.drivion.joystick_setup`. The dominance ratio
is `1.5`: at the first endpoint, the intended axis must move at least 1.5 times
as far as other eligible axes after normalizing their driver ranges. Only the
selected axis contributes to the resulting control signal.

## Check saved controls

Choose **Joystick → Check controls** to initialize the selected controller and
monitor its saved settings without recalibrating or changing configuration.
Move either stick and press Escape to return. Both this check and the pre-save
calibration check use the general `DriveMonitor` in `system/ui/drive_monitor.py`.
It adapts automatically to reverse driving and each control's response mode.

## Runtime class

```python
from car.src.config import load_config
from car.src.joystick import Joystick

with Joystick(load_config().joystick) as joystick:
    controls = joystick.read()
    print(controls.speed, controls.steering)
```

`Joystick` displays progress while resolving and opening the selected device,
validates its identity, axes and calibration, then reports successful
initialization without requiring acknowledgement. Regular initialization rejects
missing calibration. Management opens with `for_setup=True` to calibrate first.

`read()` returns an immutable `ControlInput` with normalized speed and steering.
It queries current kernel axis values rather than replaying queued input events.
Holding a stick steady remains valid without new events. Only the two configured
axes are sampled during runtime, sequentially rather than as an atomic event
frame. Poll from the application at the required control rate; there is no input
thread, exclusive device grab, automatic reconnection, or actuator integration.

An I/O failure closes the device and raises; later reads fail as well. Callers
must stop applying previous input on failure and handle reopening explicitly.
`read(controls=pending_controls)` previews validated pending settings without
modifying the saved settings. Missing axes or incompatible calibration ranges
raise `ValueError` before producing any demand and leave the device open so the
mapping can be corrected. The same checks apply to saved settings; each read
reuses the metadata from its two axis queries without extra device reads.
Use the context manager or `close()` to release the device. Calls must be
serialized. Confirm the mappings and response on the Pi before using them in
the driving loop.

## Code organization

- `discovery.py`: controller enumeration, specifications, and shared identity
  extraction and matching.
- `calibration.py`: pure dominant-axis identification and endpoint calculations;
  no device or terminal access.
- `joystick.py`: device lifetime, metadata validation, current axis snapshots,
  and control interpretation.
- `system/management/joystick_setup.py`: capture/retry prompts and atomic saving.
- `system/management/joystick_preview.py`: pre-save verification using pending
  settings; saved checks are dispatched by `system/management/joystick.py`.
- `system/ui/terminal.py`: shared single-key input and terminal restoration.
- `system/ui/drive_monitor.py`: general display of demands from any source.

`JoystickSetupConfig` validates calibration/preview metadata from
`system/pyproject.toml`; all runtime joystick settings remain in `car/config.toml`.

Reference: [python-evdev API](https://python-evdev.readthedocs.io/en/latest/apidoc.html).

Component feedback uses application logging by default. Terminal management
injects `progress` and `success` callbacks to retain its spinner and completion
message; importing or using the joystick does not import terminal UI modules.
Normal development sync preserves saved calibration in the Pi configuration;
`--replace-config` explicitly replaces it with workstation settings.
