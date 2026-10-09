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
