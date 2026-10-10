# Tests

Tests mirror the project structure: development-tool tests live under `dev/`,
application tests under `car/src/`, and system and firmware-tooling tests under
`car/system/`. Terminal-menu tests live under `car/system/ui/`.

Install the development environment and run the suite from the repository root:

```sh
uv sync --project dev
uv run --project dev pytest
```

Run a subset with `uv run --project dev pytest tests/car/src` or
`uv run --project dev pytest tests/dev`.

The suite uses local temporary files and pseudo-terminals. It does not connect
to the Pi or read local credentials. Menu tests require a Unix-like environment
with Bash and access to a controlling terminal. Python is used only by the test
harness for terminal-menu tests; the menu itself runs in Bash on the Raspberry
Pi. Application and firmware-management tests also exercise Python modules.

Native firmware tests require clang++ or g++; Arduino compilation smoke tests
require Arduino CLI and the Arduino AVR core. These tests skip when the
corresponding toolchain is unavailable. The suite does not flash connected
hardware; validate physical-device behavior separately when relevant.
