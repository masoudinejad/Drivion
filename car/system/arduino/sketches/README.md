# Arduino Nano sketches

Store Arduino sketches in this directory. Each sketch belongs in its own folder
whose name matches its primary `.ino` file.

The Raspberry Pi provisioning playbook configures this directory as Arduino
CLI's sketchbook and installs the Arduino AVR Boards core used by the Nano.

## Board setup test

`board_setup_test/board_setup_test.ino` blinks the board's built-in LED and
responds to the firmware identity query through the shared Arduino library.
Every firmware can reuse this library with its own generated identity; see
[required sketch integration](../firmware/README.md#required-sketch-integration).
It does not configure motor
pins or control motors. Blink timing is non-blocking so identity requests remain
responsive while the LED blinks.

Its only firmware parameter is
`firmware.board_setup_test.BLINK_DURATION_MS` in `car/config.toml`.
Use positive integer milliseconds. The default is 500 ms ON, then 500 ms OFF,
giving a one-second full cycle. The LED pin comes from the Arduino core's
`LED_BUILTIN` hardware definition, not an extra configurable parameter.
Its version, protocol version, board target and parameter type/range belong to
`board_setup_test/firmware.toml`, beside the sketch. This definition supplies
requirements, not fallback values. Serial baud rate and query token use shared
`[tool.drivion.firmware_flash]` settings in `system/pyproject.toml`.

From the deployed car directory:

```sh
python3 -m system.arduino.firmware.compile board_setup_test --car-root "$PWD"
```

After confirming compilation, flash the exact artifact directory it prints:

```sh
./system/env/drivion/bin/python -m system.arduino.device.flash \
    <artifact-directory> --car-root "$PWD"
```

Stop driving, make motors safe and close other serial users before confirming
upload. The flash workflow verifies the reported `board_setup_test` identity,
saves a detailed log, and updates Arduino system information.
Changing the duration requires recompilation and reflashing.

The firmware metadata targets the project's Nano (`cpu=atmega328`), not a detected
bootloader. For a Nano with the old bootloader, explicitly change its definition's
FQBN
to `arduino:avr:nano:cpu=atmega328old` before compiling. For another board, set
the appropriate FQBN in that firmware definition; USB VID/PID alone cannot select
it reliably.
