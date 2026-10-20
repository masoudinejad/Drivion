# Joystick discovery

Run system management in the configured car Python environment and choose
**Joystick → Identify and select device** to open the controller selection
list. Discovery captures hardware identifiers, button codes, and absolute axis
specifications internally. Selecting a controller saves its identity and
returns to the Joystick menu without a detail page. Back leaves the existing
setting intact. If no accessible controller is found, a diagnostic page
reports connection or permission issues.

Discovery uses the existing Linux `evdev` dependency, opens devices read-only,
and closes them after inspecting capabilities. Devices must expose absolute
axes and joystick/gamepad buttons. Inaccessible event nodes are reported;
ensure the Pi user has read access to the controller under `/dev/input`. No
input events are consumed and no speed or steering commands are sent.

The selection is saved atomically in `car/config.toml` as readable fields in
`[joystick]`: `name`, `vendor`, `product`, and `unique_id`. An empty name
means no controller has been selected. The menu title shows the saved
controller name. Matching uses the name, vendor/product and unique hardware
ID, falling back to model metadata when no unique ID is reported. It does not
depend on the volatile event number. Physical paths are captured only during
discovery for diagnostics; changes to USB ports or event numbers do not affect
matching. Without a unique ID, exactly one controller with the saved name and
hardware metadata must be connected. Multiple matching devices are rejected as
ambiguous; the software cannot distinguish identical units without unique IDs.

For future input handling, call `discover()` and
`resolve_controller(controllers, config.joystick)` to obtain the current event
path. Matching requires exactly one device; a missing controller must never
silently select another. The selection workflow rescans before saving.
Specifications are observations and are queried again rather than cached as
configuration. Axis mapping, calibration, and driving are future work.
