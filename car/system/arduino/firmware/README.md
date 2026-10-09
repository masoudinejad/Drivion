# Firmware definitions and compilation

## Compile named firmware

There are three distinct responsibilities:

- `car/config.toml` supplies firmware parameter defaults, not requirements or metadata.
- Each sketch's `firmware.toml` owns its metadata and parameter contract.
- `car/system/pyproject.toml` owns compile/flash tool settings under
  `tool.drivion.firmware_compile` and `tool.drivion.firmware_flash`.

The shared serial baud comes from `communication.baud_rate` in `car/config.toml`
and is used for header generation and firmware checks.

For the included blink test, its parameter entry in `car/config.toml` is:

```toml
[firmware.board_setup_test]
BLINK_DURATION_MS = 500
```

The name identifies its sketch folder and primary `.ino` file. Inside
`board_setup_test/firmware.toml`, the firmware declares:

```toml
[firmware]
version = "1.0.0"
protocol_version = 1
fqbn = "arduino:avr:nano:cpu=atmega328"

[parameters.BLINK_DURATION_MS]
type = "integer"
minimum = 1
maximum = 4294967295
```

Every declared parameter is required; the central config must supply exactly
those values. The compiler reads the definition and rejects missing/extra values,
wrong types, and out-of-range values before asking for confirmation. There are no
fallback parameter values in the sketch or definition. Supported declaration
types are `integer`, `number`, `boolean`, and `string`; numeric parameters can
declare `minimum` and `maximum`. Integers exclude booleans and fractional values.
Select the correct FQBN in firmware metadata; USB discovery never guesses it.
Parameter names must be uppercase C identifiers and cannot start with
`DRIVION_`. Values support booleans, AVR-range integers, finite single-precision
floats, and ASCII strings. Arrays, tables and missing/extra parameters are rejected.

The sketch includes `#include "drivion_generated.h"` (or the filename configured
in `tool.drivion.firmware_compile.header_filename`) and uses the generated
parameter macros.
Do not commit a generated header or provide fallback parameter values in code.
Firmware identity macros are `DRIVION_FIRMWARE_NAME`,
`DRIVION_FIRMWARE_VERSION`, `DRIVION_PROTOCOL_VERSION`,
`DRIVION_GIT_COMMIT`, and `DRIVION_SOURCE_DIRTY`. Commit/dirty metadata comes from
the deployed `[software]` record in `system/info.toml`; without that record the
commit is `unknown`. The dirty flag describes the deployed source snapshot, not
a clean-release guarantee. Version and protocol version come from firmware TOML.
The generated header also provides `DRIVION_SERIAL_BAUD_RATE`,
`DRIVION_INFO_COMMAND`, and `DRIVION_INFO_RESPONSE` for serial verification.
The header contains data only. The reusable Arduino identity library lives in
the configured `tool.drivion.firmware_compile.library_directory` and is copied
into each isolated build at `src/DrivionFirmware`, without modifying sketches.
This snapshot keeps retained builds independent of later library changes.
The board address remains system-wide in `[arduino].address` in `config.toml`,
not in any firmware definition; use `"auto"` or an explicit serial device path.

From the car directory, in an interactive terminal:

```sh
python3 -m system.arduino.firmware.compile board_setup_test --car-root "$PWD"
```

Python callers use `compile_firmware("board_setup_test", car_root)` from
`system.arduino.firmware.compile`. Validation and header rendering precede
the shared UI
confirmation. Refusing or ignoring approval performs no build or source writes.
After approval the compiler creates an isolated sketch copy with the generated
header, shows the shared waiting indicator, and invokes Arduino CLI.
CLI output is displayed after the waiting indicator stops, including errors.
The return value is the artifact directory, or `None` on refusal; failures raise.
Builds are retained in unique subdirectories of `tool.drivion.firmware_compile.build_directory`
(default `system/arduino/build`, ignored by Git), including failed builds for
inspection. Paths and timeout are configured only in TOML. Source files remain
unchanged. This command does not upload firmware or contact a serial port.
Successful builds also save a TOML manifest beside `artifacts`, using
`tool.drivion.firmware_compile.manifest_filename`. It records firmware identity,
FQBN,
serial baud/query settings, and SHA-256 hashes of every compiled output.
Failed or empty builds do not receive a valid manifest.

## Required sketch integration

Each sketch must initialize serial using `DRIVION_SERIAL_BAUD_RATE` and pass a
complete, null-terminated command (without newline/CR) from its existing serial
command dispatcher to the shared `drivion::handleInfo` library helper:

```cpp
#include "drivion_generated.h"
#include "src/DrivionFirmware/DrivionFirmware.h"

void setup() {
  Serial.begin(DRIVION_SERIAL_BAUD_RATE);
  // Initialize hardware in a safe state.
}

void dispatchCommand(const char *command) {
  if (drivion::handleInfo(Serial, command, DRIVION_INFO_COMMAND,
                          F(DRIVION_INFO_RESPONSE))) {
    return;
  }
  // Dispatch the firmware's other commands here.
}
```

The sketch's loop/parser must call this dispatcher whenever it receives a full
line. The helper does not consume serial bytes itself, so it cannot compete with
the motor-control parser. It replies with one JSON line containing the generated
firmware name, version, protocol version, Git commit and source-dirty flag.
The registered `board_setup_test` firmware implements this contract and blinks
the built-in LED; see [the sketchbook guide](../sketches/README.md) for its single
TOML blink-duration parameter and testing commands. It is not a motor controller.
Other sketches must implement a working dispatcher too, or upload may succeed
but the version check will correctly report failure.

## Configuration and layout validation

Compile, check, and flash share one validated configuration snapshot per workflow.
The sketchbook, shared library, build output, and flash logs must be disjoint,
including after resolving symlinks. Library staging also rejects recursive
copying independently. Central settings remain in TOML; generated manifests
capture the board and serial contract for each retained build.
