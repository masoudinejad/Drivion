# Drivion

A miniature car for learning and experimenting with machine learning and
robotics.

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
`dev/ansible/README.md` for password configuration and the SSH host-key
consideration when switching between cars.

Each Python use case has its own dependencies and lockfile. Virtual environments
are created locally and ignored by Git. Model development and tools can be
prepared with `uv sync --project model_development` and `uv sync --project
dev` from the repository root.
