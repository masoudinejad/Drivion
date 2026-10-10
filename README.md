# Drivion

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Car runtime: Python 3.13](https://img.shields.io/badge/Car_runtime-Python_3.13-blue)](car/system/pyproject.toml)
[![Platform: Raspberry Pi and Arduino](https://img.shields.io/badge/Platform-Raspberry_Pi_%2B_Arduino-green)](hardware/README.md)

An experimental miniature-car platform for learning machine learning and
robotics, built around a Raspberry Pi and an Arduino Nano.

Drivion brings together headless Raspberry Pi provisioning, camera capture,
Arduino firmware compilation and flashing, and modular serial communication.
Runtime and non-secret tool settings are centralized in TOML files.

The project is under active development: the driving entry point is currently
a placeholder, and model training and evaluation are scaffolded. It is not a
ready-to-use autonomous-driving system. The badges above describe the license
and target platform; they do not claim CI or hardware validation.

## Get started

For local development, install Python 3.11+, [uv](https://docs.astral.sh/uv/),
and Node.js with npm for Markdown checks. From a cloned repository:

```sh
uv sync --project dev
npm ci --prefix dev
uv run --project dev pre-commit install
uv run --project dev pytest
```

This prepares the development tools, not the Raspberry Pi runtime. Read the
[development guide](dev/README.md) for SSH prerequisites and local connection
settings, then follow the [provisioning guide](dev/ansible/README.md) to set up
the car. Provisioning and firmware flashing modify hardware; review their
instructions before running them.

## Documentation

- [Development and Raspberry Pi sync](dev/README.md)
- [Raspberry Pi provisioning and Wi-Fi recovery](dev/ansible/README.md)
- [Car system management](car/system/README.md)
- [Arduino discovery, firmware checks, compilation, and flashing](car/system/arduino/README.md)
- [Application modules and camera capture](car/src/README.md)
- [Pi–Arduino serial protocol](car/src/communication/README.md)
- [Hardware designs](hardware/README.md)
- [Model development](model_development/README.md)
- [Version and deployment tracking](docs/versioning.md)
- [Tests](tests/README.md) and [contributing](CONTRIBUTING.md)

## Structure

```text
car/
  drive.py               Main entry point
  config.toml            Central car settings
  src/                   Driving application modules
  system/                Setup, updates, and the car Python environment
    arduino/             Arduino tooling, firmware sources, and management UI
model_development/       Training and evaluation; independent uv project
dev/                     Development utilities; independent uv project
  sync/                  Raspberry Pi code sync and SSH setup
  quality/               Whole-project formatting and lint checks
tests/                   Automated tests, organized by project component
hardware/mechanical/     CAD and fabrication
hardware/electrical/     Schematics and wiring
docs/                    Architecture and project notes
```

The Raspberry Pi runs Python and shell scripts, controls the Arduino Nano, and
builds and flashes its firmware. The modular serial communication protocol is
documented in
[`car/src/communication/README.md`](car/src/communication/README.md); hardware
control and sensor integration remain separate application responsibilities.

## Car environment and startup

Provision from the local repository using the Pi settings in `dev/sync/.env`:

```sh
uv run --project dev python dev/ansible/run.py
```

Ansible syncs the car code and creates `system/env/drivion` under the deployed
car folder, using `/usr/bin/python3` and `--system-site-packages` for Picamera2.
The environment name and relative path are defined in `car/config.toml` under
`system.python_environment`. Runtime choices live in `car/config.toml`, while
provisioning metadata lives under `tool.drivion` in `car/system/pyproject.toml`.
Dependencies and their lockfile live in `car/system/`. The supported target is
64-bit Raspberry Pi OS with Python 3.13.
NumPy matches the OS camera stack; torch and torchvision use the CPU wheel
index.

On the Pi, run `~/car/drive.py` from any directory. The system-Python shebang
starts a small bootstrap which reads the TOML configuration and executes the
configured environment's Python. No activation or dependency installation occurs
at startup. Driving functionality is currently a placeholder.

Provisioning also configures a Wi-Fi fallback for headless access. With the
default central settings, the Pi tries its saved Wi-Fi networks for 60 seconds
and then starts a unique `Drivion-XXXXXX` hotspot if none connects. Join that
network and SSH to `driver@10.42.0.1`. Network names, timing, interface, and
address are configured under `system.network` in `car/config.toml`. See
[the provisioning guide](dev/ansible/README.md) for password configuration and
the SSH host-key
consideration when switching between cars.

Each Python use case has its own dependencies and lockfile. Virtual environments
are created locally and ignored by Git. Model development and tools can be
prepared with `uv sync --project model_development` and `uv sync --project
dev` from the repository root.

## Contributing and support

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup, quality checks, and commit
guidelines. Report reproducible problems or propose improvements through
[GitHub issues](https://github.com/masoudinejad/Drivion/issues). Do not include
credentials, private connection settings, or unredacted logs.

## License

Drivion is licensed under the [Apache License 2.0](LICENSE).
