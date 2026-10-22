# Car system management

Setup and update tools live here. The car Python environment uses Raspberry Pi
OS Python with system package access for Picamera2. See the root README for
setup commands. The Arduino CLI sketchbook and Pi-side build and flash scripts
live in `arduino/`.

Reusable terminal interactions live in `ui/`. See the
[UI instructions](ui/README.md) for menu and typed-question usage.

System settings are read from the central `../config.toml` by
`configuration.py`. Boot-time information publishing lives in `information/`,
and Wi-Fi fallback behavior lives in `network/`. Provisioning installs protected
copies of those service modules under `/usr/local/lib/drivion/`; systemd never
executes the user-writable deployed copies as root.

Provisioning also snapshots `config.toml`, `system/pyproject.toml`, and the
Arduino CLI configuration into the root-owned service configuration directory.
Root services read only that protected snapshot, so changing editable deployment
files cannot change a root executable or command configuration until Ansible
validates and installs the new state.

## Central hardware and software evaluation

`information.update.refresh_info()` runs the initial evaluations together at
**Pi boot** and atomically writes `system/info.toml`. Automatic boot checks
cover configuration and hardware; they skip environment/dependency verification.
Full software verification is reserved for provisioning or explicit requests.
`drive.py` only enters the
configured Python environment, validates the live configuration, and displays
the last saved report; it never runs the full evaluation or changes its
timestamp.
Code sync only updates deployment metadata while preserving the last evaluation.
Provisioning explicitly runs the central check after installing dependencies;
its package consistency check remains an installation-specific check.

The generated snapshot contains:

- `checks`: overall status, UTC evaluation time, evaluated deployment commit,
and
  sections requiring attention. Compare `evaluated_commit` with
`software.commit`
  to see whether the latest code has been evaluated.
- `software`: deployed version, commit, dirty flag, checksum, and deployment
time.
  These are preserved deployment records, not a fresh integrity verification.
- `configuration`: validation of the complete application configuration.
- `environment`: `status = "not_checked"` during normal boot checks. Explicit
  full checks record Python path, executable, version, and every declared
  dependency's installed version, import result, and failure details, including
  system imports. `checks.environment_checked` records which mode was used.
- `hardware`: Raspberry Pi model and serial number.
- `camera`: all detected camera models, connection IDs, indexes, and available
  location/rotation fields. IDs are connection identities, not module serials.
- `arduino`: discovered ports, USB identity, selection, and any retained
firmware
  observation, explicitly marked as historical by the existing firmware fields.
- `joystick`: detected controller identities and paths, discovery errors, and
  whether the saved selection resolves to one connected device.
- `system`: hostname, operating system, kernel, and architecture.
- `network`: configured Wi-Fi interface and fallback SSID/address. This records
  network identity; it does not test connectivity.

Each evaluated section has a status. Missing devices, invalid configuration,
missing environments, failed imports, and discovery failures are saved in the
new snapshot instead of leaving stale identities or aborting unrelated checks.
The driving screen labels these as saved results and displays their timestamp;
it does not use old results to reject the current runtime. The launcher still
rejects an invalid live configuration or missing Python environment immediately.
The information-update CLI returns success when the snapshot was published;
inspect
`checks.status` and per-section statuses for readiness. Hotspot-update errors
still produce an unsuccessful exit. `--require-runtime`, used by provisioning,
requests the full environment check and exits unsuccessfully for configuration
or environment evaluation failures. Skipped environment checks are informational
and do not count as failed hardware readiness checks.

When requested, dependency imports run in isolated subprocesses using the
configured environment.
The root boot collector drops to the car directory owner's UID, GID and group
memberships before executing the user-managed environment or deployed worker.
Its own modules and configuration remain protected. Per-import and whole-worker
timeouts live under `tool.drivion.verification` in `system/pyproject.toml`;
numerical thread limits use `tool.drivion.execution`. Full import checks can
take
some time on a Pi. The boot service uses these internal bounds instead of
systemd's shorter default startup timeout.

The initial evaluation does not capture frames, reset/open Arduino serial
communication, consume joystick input, or drive actuators. Use **Hardware
tests**
for functional and latency diagnostics. Those tests keep their detailed logs.

Inspect the snapshot with `cat ~/car/system/info.toml` or **System Info**.
Refresh
it explicitly from the car directory with:

```sh
./system/env/drivion/bin/python -m system.information.update --car-root .
--print
```

Add `--check-environment` to that command for the full dependency version/import
sweep. Normal boot and manual hardware refreshes do not import the full stack.

The record is separate from `config.toml` and should not be edited. Moving the
SD card to another Pi updates the hardware record and hotspot SSID at boot.

## System management

Open the central menu from the car directory (Python 3.11 or newer):

```sh
./system/manage.py
```

It can also be launched by absolute path from any working directory. Use an
interactive ANSI terminal, including SSH. Arrow keys select a category; Enter
opens it; Back or Escape exits the main menu; Ctrl-C cancels with status 130.
The first category, **System Info**, reloads `system/info.toml` on every visit
and shows all software, hardware, system, and network fields using the shared
UI theme. Scroll the terminal to inspect long output and press Enter to return.
Missing or malformed information is displayed as an error page, after which
the menu remains usable. This view reads the published snapshot; it does not
refresh hardware information or change configuration. No root access is needed.
The executable launcher enters the configured car
Python environment automatically. Provision it with Ansible before launching.

`manage.py` is the entry point. `management/application.py` owns navigation and
the `MenuItem` registry; `ui/navigation.py` adapts the existing Bash menu and
provides read-only pages. `information/view.py` handles loading and rendering
information separately from boot-time publishing in `information/update.py`.
To add setup, settings, or administration features, implement an action
accepting
the car root and register a `MenuItem` in `default_items()`. Actions may compose
submenus with the same UI helpers. Only implemented categories appear in the
menu. Future configurable behavior belongs in `car/config.toml`; styling stays
in `ui/theme.toml`.

## Arduino management

The executable launcher selects the car Python environment from `config.toml`:

```sh
./system/manage.py
```

Open **Arduino → Identify and select device**. Discovery runs with the shared
waiting indicator and lists every connected port, including unidentified USB
adapters. Select a device to save its address to `arduino.address` through the
validated, atomic config modifier. Back leaves configuration unchanged. The
connection and USB properties are checked again before saving; a disconnected
or changed device requires another scan. Without a USB serial number, adapters
sharing an address and VID/PID cannot be distinguished reliably.

The result page shows observed device specifications and board candidates.
Sketchbook location remains a user setting; board FQBN and bootloader choices
remain specific to each firmware and are not inferred from USB discovery.
Comments and unrelated settings in `config.toml` are preserved. Applications
must reload configuration to see the selected address. A later code sync mirrors
the local config over the Pi's copy, so preserve the desired address locally
before syncing again. This operation does not compile, flash, or reset a board.

An empty `arduino.address = ""` means no device has been selected yet.
Identification still lists connected devices; selecting one saves its address.
Flashing requires a selected address or an unambiguous `auto` target.

### Change Arduino firmware

Open **Arduino → Change firmware** to list firmware registrations from the
central `[firmware]` TOML table. Parameter values come from that table;
versions,
board FQBNs and required parameter contracts come from each sketch's own
`firmware.toml`. Build/serial settings live in system tool metadata TOML.
Select one to run the existing compile procedure and then flash its returned
artifact directory using the existing verified-flash procedure. Each step keeps
its confirmation and progress UI. Back or a refused confirmation stops the
workflow; failed compilation never triggers uploading. Missing sketches and
invalid settings are reported without uploading.

Successful completion displays the artifact and flash-log paths after verifying
the running firmware identity. Failed uploads or verification show an error and
retain the existing detailed logs. Operations return to the Arduino submenu.
See [Arduino instructions](arduino/README.md) for firmware registration,
sketch integration, and the compile/flash contracts.

### Check running Arduino firmware

Open **Arduino → Check firmware** to query the selected device using the
existing
firmware-check procedure. Its confirmation and waiting indicators are preserved.
The result page shows the reported identity or query error and observation time;
Enter returns to the Arduino submenu. Declining confirmation returns directly.
This updates system information using the check procedure; it does not compile
or upload. A reported identity is not verification against a compiled build.

## Hardware tests

Open `manage.py` and select **Hardware tests**. The camera check captures the
configured number of frames, validates their shape/type, and reports capture
latencies and observed throughput. The Arduino communication check negotiates
with compatible running communication firmware, repeats clock synchronization
and correlated telemetry requests, and requires fresh status. Stop driving and
close other serial users first: opening the port may reset the board. The check
sends no movement targets and does not flash firmware.

The **Joystick check** uses the saved controller and calibration. First select
and configure the joystick under **Joystick** if needed. The check opens a live
control display: move both speed and steering, then press Enter to finish.
Enter is ignored until both controls change. Escape records `CANCELLED` without
reporting a pass; Ctrl-C records `INTERRUPTED`, and disconnects record `FAIL`.
The check logs axis metadata, changes in normalized demands, initialization
time, and read count with minimum/mean/maximum read duration. Input changes are
written only to the saved log/report so they do not flash over the live bars.
It sends no driving
commands and does not modify calibration. Read duration measures kernel queries
and normalization, not physical controller-to-host latency. Refresh and
idle-hint
timing reuse `[tool.drivion.joystick_setup]` in `system/pyproject.toml`. Read
statistics use constant memory, even during a long interactive check.

Each run prints progress and results to the terminal and writes a separate
UTC-timestamped `.log` file under the `[hardware_tests].log_directory` path,
relative to the car root. Failures include tracebacks; cancellation records an
interrupted result. The result page includes the log path. Configure frame
count,
Arduino sample count, and response timeout in `[hardware_tests]` in
`car/config.toml`; camera and serial settings come from their existing sections.

Latencies are host monotonic-clock measurements in milliseconds. Every sample
and its minimum, mean, median, and maximum are logged for camera and Arduino
checks. Camera capture latency
measures the blocking capture call, including frame delivery and array handling;
it does not measure exposure-to-display latency. Initialization and configured
warmup are excluded from capture throughput. Arduino handshake and telemetry
latencies measure host request/response round trips, including serial I/O and
polling; they are not one-way delays. Initial connection time includes the board
boot wait and is reported separately. Missing replies fail after the configured
response timeout (subject to an in-progress serial read). Camera capture uses
the
camera driver's blocking call; an unresponsive driver may require interruption.

Generated information is a recoverable cache: malformed `system/info.toml`
records are reported and rebuilt without reusing invalid metadata. Wi-Fi
fallback
is ordered after information refresh but does not require refresh to succeed,
so recovery access remains available when information collection fails.
Hardware diagnostics require the optional `[hardware_tests]` section; if absent,
management displays a configuration message and returns to its menu.

Use hardware diagnostics on the Pi to measure camera throughput and Arduino
round-trip latency before changing performance budgets. Desktop tests cannot
establish physical-device timing, memory use, or camera compatibility. Keep the
current ML dependency contract until representative model workloads identify
which frameworks can be removed or made optional.
