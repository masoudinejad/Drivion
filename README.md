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
    arduino/firmware/    Arduino Nano C/C++ firmware
    arduino/scripts/     Build and flash tools run on the Pi
model_development/       Training and evaluation; independent uv project
dev_tools/              Development utilities; independent uv project
hardware/mechanical/     CAD and fabrication
hardware/electrical/     Schematics and wiring
docs/                    Architecture and project notes
```

The Raspberry Pi runs Python and shell scripts, controls the Arduino Nano, and
builds and flashes its firmware. Hardware details and the communication protocol
will be defined in later steps.

## Car environment and startup

On Raspberry Pi OS, from `car/`:

```sh
sudo apt install python3-picamera2
uv venv --python /usr/bin/python3 --system-site-packages system/.venv
uv sync --project system
./drive.py
```

The environment inherits OS-managed Picamera2 and camera dependencies.
Additional Python dependencies belong in `car/system/pyproject.toml`; avoid
overriding camera stack packages with uv packages. The system Python version
must satisfy the project requirements.

Run `./drive.py` from `car/`. Its shebang selects the prepared environment
through uv without activation. It uses `--no-sync` so starting the car does not
install or update dependencies. The entry point is currently a placeholder.

Each Python use case has its own dependencies and lockfile. Virtual environments
are created locally and ignored by Git. Model development and tools can be
prepared with `uv sync --project model_development` and `uv sync --project
dev_tools` from the repository root.
