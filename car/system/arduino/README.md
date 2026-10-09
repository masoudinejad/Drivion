# Arduino firmware and board discovery

## Compile named firmware

Register each firmware in `car/config.toml`. The name identifies its sketch
folder and primary `.ino` file inside the configured sketchbook. For example,
`motor_controller` requires `motor_controller/motor_controller.ino`:

```toml
[firmware.motor_controller]
version = "1.0.0"
protocol_version = 1
fqbn = "arduino:avr:nano:cpu=atmega328"
required_parameters = ["MOTOR_PIN", "MAX_SPEED"]

[firmware.motor_controller.parameters]
MOTOR_PIN = 5
MAX_SPEED = 180
```

This is a registration example, not an implemented motor firmware. Select the
correct FQBN explicitly; compilation never guesses the board or bootloader.
Each firmware lists its required parameters and supplies exactly those values.
Parameter names must be uppercase C identifiers and cannot start with
`DRIVION_`. Values support booleans, AVR-range integers, finite single-precision
floats, and ASCII strings. Arrays, tables and missing/extra parameters are rejected.

The sketch includes `#include "drivion_generated.h"` (or the filename configured
in `firmware_compile.header_filename`) and uses the generated parameter macros.
Do not commit a generated header or provide fallback parameter values in code.
Firmware identity macros are `DRIVION_FIRMWARE_NAME`,
`DRIVION_FIRMWARE_VERSION`, `DRIVION_PROTOCOL_VERSION`,
`DRIVION_GIT_COMMIT`, and `DRIVION_SOURCE_DIRTY`. Commit/dirty metadata comes from
the deployed `[software]` record in `system/info.toml`; without that record the
commit is `unknown`. The dirty flag describes the deployed source snapshot, not
a clean-release guarantee. Version and protocol version come from firmware TOML.
The generated header also provides `DRIVION_SERIAL_BAUD_RATE`,
`DRIVION_INFO_COMMAND`, and `drivionHandleInfo(command)` for serial verification.

From the car directory, in an interactive terminal:

```sh
python3 -m system.arduino.compile motor_controller --car-root "$PWD"
```

Python callers use `compile_firmware("motor_controller", car_root)` from
`system.arduino.compile`. Validation and header rendering precede the shared UI
confirmation. Refusing or ignoring approval performs no build or source writes.
After approval the compiler creates an isolated sketch copy with the generated
header, shows the shared waiting indicator, and invokes Arduino CLI.
CLI output is displayed after the waiting indicator stops, including errors.
The return value is the artifact directory, or `None` on refusal; failures raise.
Builds are retained in unique subdirectories of `firmware_compile.build_directory`
(default `system/arduino/build`, ignored by Git), including failed builds for
inspection. Paths and timeout are configured only in TOML. Source files remain
unchanged. This command does not upload firmware or contact a serial port.
Successful builds also save a TOML manifest beside `artifacts`, using
`firmware_compile.manifest_filename`. It records firmware identity, FQBN,
serial baud/query settings, and SHA-256 hashes of every compiled output.
Failed or empty builds do not receive a valid manifest.

## Flash and verify a compiled build

Use the provisioned Python environment (includes `pyserial`) and an interactive
terminal. Stop driving, disconnect motor power or otherwise make the motors
safe, and close other serial users first. Uploading and subsequently opening
serial may reset the board and run its startup code.

Pass the exact artifact directory returned by compilation:

```sh
./system/env/drivion/bin/python -m system.arduino.flash \
    system/arduino/build/motor_controller-<build-id>/artifacts --car-root "$PWD"
```

Replace the example path with your actual build directory; use the configured
environment path if customized. Python callers use
`flash_firmware(artifact_directory, car_root)` from `system.arduino.flash`.
It returns the detailed log path on verified success, `None` on refusal, and
raises `FlashError` (with a `log_path` attribute) on a failed confirmed attempt.
Ctrl-C interrupts and still finalizes the attempted-flash log.

The function validates the compile manifest and artifact hashes, discovers the
configured Arduino address, and asks the existing UI for confirmation. It
rechecks the target and hashes after approval, uploads via Arduino CLI with
binary verification, and shows waiting indicators during detection, upload,
and firmware verification. The manifest supplies the target FQBN and serial
baud/query contract; changing live firmware settings cannot relabel an old build.
Older builds without a manifest must be compiled again.

Every confirmed attempt creates a uniquely named TOML log in
`firmware_flash.log_directory` (default `system/arduino/logs`). Logs include
timestamps, target USB properties, binary hashes, upload command, verbose CLI
stdout/stderr and exit status, expected and observed identities, serial replies,
and failure details. Upload success and identity verification are separate
statuses; a missing/malformed reply or identity mismatch is a failed verification,
not proof that uploading failed. Log creation must succeed before any upload,
and the serial dependency is checked before confirmation or upload.
No logs/builds are created for a refused confirmation. Sync preserves configured
build and log directories instead of deleting them; these outputs are not deployed.
The log directory must not overlap the sketchbook or build directory.

The selected port's flat Arduino system-information fields include
`firmware_name`, `firmware_version`, `firmware_protocol_version`,
`firmware_git_commit`, `firmware_source_dirty`, `firmware_status`,
`firmware_upload_status`, `firmware_checked_at`, and `firmware_log`.
Only an actual serial response supplies identity fields. A mismatch records
what the board reported; a failed upload/query clears previously cached identity
for the affected port. Other ports and system-information sections are preserved.
These are timestamped observations, not continuous monitoring. Ordinary discovery
and boot/sync refresh retain cached identity only when address and USB properties
match and label a previously verified observation `last_verified`; they do not
open/reset the board. Disconnecting/changing USB identity drops that cache.
An adapter without a USB serial number cannot prove that a replacement board
with the same VID/PID and address is the original device.

Baud rate, query token, boot settling time, bounded serial timeouts and reply
limit, upload timeout, and log directory are all in `[firmware_flash]` in
`config.toml`. The generated identity must fit the configured response limit.
Verification currently queries the original serial address. Native-USB boards
that re-enumerate to a different address may upload successfully but fail this
check; the log retains that distinction rather than guessing another device.
Flashing callers must serialize hardware access and system-info updates with
other management operations; no drive process is automatically stopped.

### Required sketch integration

Each sketch must initialize serial using `DRIVION_SERIAL_BAUD_RATE` and pass a
complete, null-terminated command (without newline/CR) from its existing serial
command dispatcher to the generated `drivionHandleInfo(command)` helper:

```cpp
#include "drivion_generated.h"

void setup() {
  Serial.begin(DRIVION_SERIAL_BAUD_RATE);
  // Initialize hardware in a safe state.
}

void dispatchCommand(const char *command) {
  if (drivionHandleInfo(command)) {
    return;
  }
  // Dispatch the firmware's other commands here.
}
```

The sketch's loop/parser must call this dispatcher whenever it receives a full
line. The helper does not consume serial bytes itself, so it cannot compete with
the motor-control parser. It replies with one JSON line containing the generated
firmware name, version, protocol version, Git commit and source-dirty flag.
No sketch is currently registered in this repository; this is the integration
contract, not an implemented motor controller. Without a working dispatcher,
upload may succeed but the version check will correctly report failure.

## Discover connected boards

On the Pi, run from the deployed car directory:

```sh
cd ~/car
python3 -m system.arduino.discover --car-root "$PWD"
```

The command prints a short summary of ports, board candidates, USB serial
numbers, VID/PID, FQBNs, and any errors. Add `--verbose` to print the full JSON
report:

```sh
python3 -m system.arduino.discover --car-root "$PWD" --verbose
```

Both modes save only compact board identity and errors to the `arduino` section
in
`system/info.toml`, preserving other sections. The usual system-information
refresh also collects Arduino information at boot and after sync. Run discovery
again after plugging in or removing a board.

For one connected port, the saved `[arduino]` section directly contains status,
identification, matching boards, address, protocol, serialNumber, VID, and PID
when provided. Multiple ports retain separate `[[arduino.ports]]` entries so
no device is discarded. An empty serialNumber means USB provided no serial.

Only `address` and `sketchbook_directory` are user settings under `arduino` in
`config.toml`. Set `address = "auto"` when exactly one serial port will be present;
with multiple ports, configure the exact address reported by discovery. Discovery
never guesses a board, selects among multiple ports, or rewrites configuration.

Pinned CLI/core metadata, protected paths, and execution timeouts live under
`tool.drivion.arduino` in `system/pyproject.toml`. Interactive discovery uses the
car user's Arduino CLI configuration; the root boot service uses the protected
copy installed by Ansible. No firmware is uploaded or compiled.

The verbose report retains all CLI port properties (including USB VID/PID and serial
number when provided), every candidate name/FQBN, installed core metadata, and
full board details including configuration options, upload tools, programmers,
and build specifications when available. Missing CLI/core or detail failures
are reported as errors or partial results rather than successful empty scans.

Board options describe the core's supported choices and defaults, not measured
processor or bootloader settings. USB serial adapters used by classic Nanos and
clones may be unidentified; detection does not guess their board model.
