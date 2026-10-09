# Arduino device operations

## Flash and verify a compiled build

Use the provisioned Python environment (includes `pyserial`) and an interactive
terminal. Stop driving, disconnect motor power or otherwise make the motors
safe, and close other serial users first. Uploading and subsequently opening
serial may reset the board and run its startup code.

Pass the exact artifact directory returned by compilation:

```sh
./system/env/drivion/bin/python -m system.arduino.device.flash \
    system/arduino/build/motor_controller-<build-id>/artifacts --car-root "$PWD"
```

Replace the example path with your actual build directory; use the configured
environment path if customized. Python callers use
`flash_firmware(artifact_directory, car_root)` from
`system.arduino.device.flash`.
It returns the detailed log path on verified success, `None` on refusal, and
raises `FlashError` (with a `log_path` attribute) on a failed confirmed attempt.
Ctrl-C interrupts and still finalizes the attempted-flash log.

The function validates the compile manifest and artifact hashes, discovers the
configured Arduino address, and asks the existing UI for confirmation. It
rechecks the target and hashes after approval, uploads via Arduino CLI with
binary verification, and shows waiting indicators during detection, upload,
and firmware verification. The manifest supplies the target FQBN and serial
baud/query contract; changing live firmware settings cannot relabel an old
build.
Older builds without a manifest must be compiled again.

Every confirmed attempt creates a uniquely named TOML log in
`tool.drivion.firmware_flash.log_directory` (default `system/arduino/logs`).
Logs include
timestamps, target USB properties, binary hashes, upload command, verbose CLI
stdout/stderr and exit status, expected and observed identities, serial replies,
and failure details. Upload success and identity verification are separate
statuses; a missing/malformed reply or identity mismatch is a failed
verification,
not proof that uploading failed. Log creation must succeed before any upload,
and the serial dependency is checked before confirmation or upload.
No logs/builds are created for a refused confirmation. Sync preserves configured
build and log directories instead of deleting them; these outputs are not
deployed.
The log directory must not overlap the sketchbook or build directory.

The selected port's flat Arduino system-information fields include
`firmware_name`, `firmware_version`, `firmware_protocol_version`,
`firmware_git_commit`, `firmware_source_dirty`, `firmware_status`,
`firmware_upload_status`, `firmware_checked_at`, and `firmware_log`.
Only an actual serial response supplies identity fields. A mismatch records
what the board reported; a failed upload/query clears previously cached identity
for the affected port. Other ports and system-information sections are
preserved.
These are timestamped observations, not continuous monitoring. Ordinary
discovery
and boot/sync refresh retain cached identity only when address and USB
properties
match and label a previously verified observation `last_verified`; they do not
open/reset the board. Disconnecting/changing USB identity drops that cache.
An adapter without a USB serial number cannot prove that a replacement board
with the same VID/PID and address is the original device.

The shared baud rate is in `[communication]` in `car/config.toml`. Query token,
boot settling time, bounded serial timeouts and reply limit, upload timeout,
and log directory are in `[tool.drivion.firmware_flash]` in
`system/pyproject.toml`. The generated identity must fit the configured
response limit.
Verification currently queries the original serial address. Native-USB boards
that re-enumerate to a different address may upload successfully but fail this
check; the log retains that distinction rather than guessing another device.
Flashing callers must serialize hardware access and system-info updates with
other management operations; no drive process is automatically stopped.

## Check running firmware independently

Query the currently selected Arduino without compiling or uploading:

```sh
./system/env/drivion/bin/python -m system.arduino.device.check --car-root "$PWD"
```

Use the configured environment path if customized. Python callers use
`check_firmware(car_root)` from `system.arduino.device.check`.
It returns `None` when
confirmation is declined, otherwise a report with status, address, timestamp,
query transcript and either the observed `firmware` identity or an error.
Configuration/dependency/selection failures raise before opening serial.
The terminal summary is concise; `--verbose` includes the serial transcript.

The existing confirmation UI warns that opening serial may reset/start the
board. Stop driving, make motors safe, and close other serial users first.
Waiting indicators cover discovery, target rechecking, and the firmware query.
No build artifacts or flash logs are needed, and firmware need not be registered
locally: the identity comes only from the board's response.

The command updates the selected port's flat firmware fields in
`system/info.toml`
without changing other sections/ports or removing the last flash log/upload
status. Success is `firmware_status = "reported"`, not verification against a
compiled build. Failed/interrupted queries remove stale identity fields and save
an error/status with a fresh timestamp; they do not erase flash history.
Ordinary discovery/boot refresh marks a cached successful check `last_reported`
and retains its timestamp. It never silently performs another serial query.

Serial settings come from `[tool.drivion.firmware_flash]` in
`system/pyproject.toml`, with the shared baud from `communication.baud_rate` in
`car/config.toml`. Baud and query token must match the running firmware. The
sketch must implement the
identity handler; firmware without it remains unknown. The original-port and
USB identity limitations described above also apply. This function is standalone
and does not automatically run at startup or stop other serial users.

## Discover connected boards

On the Pi, run from the deployed car directory:

```sh
cd ~/car
python3 -m system.arduino.device.discovery --car-root "$PWD"
```

The command prints a short summary of ports, board candidates, USB serial
numbers, VID/PID, FQBNs, and any errors. Add `--verbose` to print the full JSON
report:

```sh
python3 -m system.arduino.device.discovery --car-root "$PWD" --verbose
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
`config.toml`. Leave `address = ""` before selecting a device in system
management.
Set `address = "auto"` when exactly one serial port will be present;
with multiple ports, configure the exact address reported by discovery.
Discovery
never guesses a board, selects among multiple ports, or rewrites configuration.

Pinned CLI/core metadata, protected paths, and execution timeouts live under
`tool.drivion.arduino` in `system/pyproject.toml`. Interactive discovery uses
the
car user's Arduino CLI configuration; the root boot service uses the protected
copy installed by Ansible. No firmware is uploaded or compiled.

The verbose report retains all CLI port properties (including USB VID/PID and
serial
number when provided), every candidate name/FQBN, installed core metadata, and
full board details including configuration options, upload tools, programmers,
and build specifications when available. Missing CLI/core or detail failures
are reported as errors or partial results rather than successful empty scans.

Board options describe the core's supported choices and defaults, not measured
processor or bootloader settings. USB serial adapters used by classic Nanos and
clones may be unidentified; detection does not guess their board model.

## Operation failures

Flash finalization attempts both the system-information update and log write,
even if either fails. The original upload or query error remains the primary
error, with the log path and any persistence errors attached. Interruptions keep
their cancellation semantics. A missing initial log prevents uploading.

Target checks use lightweight discovery: one board-list command per scan.
Full discovery enriches the report with installed cores and board specifications
when explicitly requested through the discovery command or system information.
