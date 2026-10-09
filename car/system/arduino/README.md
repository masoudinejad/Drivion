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

CLI paths come from `arduino.provisioning` and execution/discovery timeouts from
`arduino.discovery` in `config.toml`. The deployed car directory's parent anchors
the home-relative CLI configuration path, including during the boot service.
No firmware is uploaded or compiled.

The verbose report retains all CLI port properties (including USB VID/PID and serial
number when provided), every candidate name/FQBN, installed core metadata, and
full board details including configuration options, upload tools, programmers,
and build specifications when available. Missing CLI/core or detail failures
are reported as errors or partial results rather than successful empty scans.

Board options describe the core's supported choices and defaults, not measured
processor or bootloader settings. USB serial adapters used by classic Nanos and
clones may be unidentified; detection does not guess their board model.
