# Arduino board discovery

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
