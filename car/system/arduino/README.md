# Arduino tooling

This directory separates firmware sources, host tooling, and interactive menus.

```text
arduino/
  settings.py         Shared TOML readers, validation, and workflow context
  firmware/           Definitions, identity, artifacts, and compilation
  device/             Discovery, serial protocol, status, checking, and flashing
  management/         Device selection menu and firmware-change workflow
  sketches/           Firmware sketches, each with its own firmware.toml
  library/            Shared Arduino C++ identity handler
  build/              Generated isolated builds (ignored by Git)
  logs/               Generated flash records (ignored by Git)
```

The build and log locations follow `system/pyproject.toml`; the sketchbook follows
`config.toml`. Python tooling lives in packages, outside the sketchbook.

- [Firmware definitions and compilation](firmware/README.md)
- [Discovery, flashing, and firmware checks](device/README.md)
- [Included board setup sketch](sketches/README.md)

## Management workflow

Run `./system/manage.py` from the car checkout and select **Arduino**:

1. **Identify and select device** scans ports and saves `arduino.address`.
2. **Change firmware** selects a valid registered sketch, compiles it, and flashes
   the exact returned artifact directory after confirmation.
3. **Check firmware** queries the selected board without compiling or uploading.
4. **Configure steering servo** edits numeric settings such as the pin and timeout.
5. **Guided servo calibration** discovers straight, direction, and travel limits
   by moving the connected servo and asking the user to observe the wheels.

Invalid firmware entries are reported individually. Healthy entries remain
selectable; the selected definition is validated again before compilation.
Declining confirmation or choosing Back stops the workflow.

## Command-line entry points

From the car directory, using the provisioned Python environment:

```sh
python -m system.arduino.firmware.compile board_setup_test --car-root "$PWD"
python -m system.arduino.device.discovery --car-root "$PWD"
python -m system.arduino.device.check --car-root "$PWD"
python -m system.arduino.device.flash <artifact-directory> --car-root "$PWD"
```

The previous flat Python module paths have moved into the packages above.
Flashing and opening serial can reset/start the board. Stop driving, make motors
safe, close other serial users, and serialize hardware operations before running
flash or check. Detailed contracts and limitations are in the device guide.

## Steering servo

Use management → Arduino → Configure steering servo to edit the central
`car/config.toml` calibration, preview it, and save it atomically. Then use
Change firmware → steering to compile and flash the new values. Restart the Pi
application after flashing so both sides use the same configuration. Saving
settings alone does not change a running Arduino. The system update provisions
the pinned Arduino Servo library from `system/pyproject.toml`.

`STEERING_LEFT_DEG` and `STEERING_RIGHT_DEG` are positive physical steering
magnitudes. The Pi's `Communication.set_normalized_target(speed_mm_s, steering,
config.firmware["steering"])` converts normalized -1 through +1 into the existing
centidegree wire protocol. The Arduino clamps these demands and interpolates
separately from `SERVO_CENTER_DEG` toward `SERVO_LEFT_DEG` or `SERVO_RIGHT_DEG`.
For inverted steering, set left above center and right below center, for example
150/90/30. Center must lie strictly between the two endpoints.

The default signal pin is Nano D9. Any digital-capable pin D2–D19 can be selected;
D0/D1 remain reserved for serial. Arduino Servo generates timed servo pulses
using Timer1, so ordinary `analogWrite()` on D9/D10 is unavailable while attached.
This is a servo control signal, not high-frequency motor PWM. The configured
pulse bounds (default 1000–2000 µs, allowed 544–2400 µs) describe absolute servo
0–180 degrees; match these and endpoint angles to the servo's specification.
Use a suitable servo supply with ground shared with the Nano.

The firmware starts straight and returns straight on STOP, a new session, an
expired command, or `STEERING_TIMEOUT_MS` without an accepted target (default
1000 ms). Invalid, replayed, corrupt, and unrelated frames do not refresh this
timer. Timeout arithmetic handles `millis()` wraparound. Management keeps the
communication watchdog lease equal to the steering timeout. The Pi's existing
`communication.command_validity_ms` may expire commands sooner (default 150 ms);
it must not exceed that lease. Send fresh targets regularly, even when unchanged.
The loop must keep running for timeout handling; this does not provide protection
against loss of power, mechanical faults, or a halted MCU. Telemetry does not
claim servo position without a physical sensor. This firmware does not actuate
the drive motor. Hardware travel and disconnect behavior still need bench testing.

### Guided calibration on the car

Flash the current `steering` firmware (version 1.1.0 or newer) first. If the
signal pin or pulse range needs changing, save that through **Configure steering
servo**, then flash before opening the wizard. An unsupported or mismatched
firmware rejects calibration; movement remains bounded by the firmware's own
settings. The running pin, pulse range, initial pulse, nudge bound, and timeout
are checked with a shared settings checksum.

Choose **Arduino → Guided servo calibration**. Stop driving, disconnect the
drive motor's power, lift the wheels, and close other serial users before
starting. Servo signal output initially uses the configured straight position;
its physical meaning is still unknown, so keep clear of the linkage.

1. Use **a/d** for small decreases/increases and **Shift+A/D** for coarse steps.
   Watch the wheels; press **Enter** when they point straight. A 90-degree
   straight value is never assumed to be physically correct.
2. Make another small nudge, then press **l** or **r** to report which way the
   wheels turned, viewed from behind the car facing forward. This determines
   whether increasing the pulse steers left or right.
3. For each endpoint, **a** now means move physically left and **d** means right,
   including with an inverted servo. Stop at the desired usable travel before
   mechanical binding and press **Enter**. The wizard returns through straight
   between endpoints.
4. Test **l** (left), **r** (right), and **s** (straight). All three must be tested;
   finish at straight, press **Enter**, review the discovered values, and save.
   The wizard then offers the existing compile-and-flash workflow to apply them.

**q/Escape** or **Ctrl+C** cancels without saving. **x** immediately disables the
servo signal. **n** reports no movement and suggests checking wiring, power,
the signal pin and firmware. **c** reports continuous rotation and disables the
signal: continuous-rotation servos require position feedback or replacement with
a positional servo for this steering system. The user supplies these
observations; there is no automatic sensing of position or servo type.

Each movement is acknowledged, limited to `CALIBRATION_STEP_US` (default 25 µs),
and constrained to the compiled pulse range. Verification movements also advance
in bounded steps. TOML-owned fine/coarse steps, polling, heartbeat, acknowledgement
and synchronization timing live in `[tool.drivion.steering_calibration]` in
`system/pyproject.toml`. Human thinking time is unrestricted while communication
remains healthy. A missed lease aborts calibration and cannot be rearmed by a
late heartbeat. Stop, cancellation or a new session returns to the straight
position marked during this session. Before straight is known the signal is
disabled; explicit disable remains off even across subsequent handshakes.
Disabling pulses does not guarantee a mechanical return to straight.

Normal drive targets remain blocked after calibration begins, including after
cancellation, until board restart or reflash. Restart alone restores the old
compiled calibration. Saved calibration must be flashed before driving with the
new values. Changes are saved atomically only after verification and confirmation;
the learned fallback is temporary until flashed. The physical steering-angle
limits are preserved because a visual wizard cannot measure wheel angles.
