# Raspberry Pi automation

Run the first maintenance playbook from the repository root:

```sh
uv sync --project dev
uv run --project dev python dev/ansible/run.py --syntax-check
uv run --project dev python dev/ansible/run.py --check
uv run --project dev python dev/ansible/run.py
```

The runner reads `dev/sync/.env`. It uses `PI_HOST` and `PI_USER` for the target,
the existing SSH agent/public-key settings for login, and `PI_PASSWORD` for
sudo. It does not enable passwordless sudo or change SSH authentication.
The password is passed through the subprocess environment, not command arguments
or generated inventory files. Keep `.env` ignored and restricted to your user.

Ansible runs locally; the Pi needs SSH, `/usr/bin/python3`, python3-apt, and sudo.
The playbook refreshes the apt index and performs a standard package upgrade.
It preserves existing configuration files using the apt module defaults.
It does not perform a distribution upgrade, autoremove packages, or reboot.
Package upgrades may restart affected services.

After the upgrade, it ensures Picamera2, Python venv/apt support, headless camera
diagnostics, rsync, curl, wget, CA certificates, and Git are installed. Optional
desktop recommendations are disabled. Picamera2's required dependencies are
installed automatically, and its import is verified using system Python.

It installs uv and uvx into `/usr/local/bin`, using the pinned official ARM64
archive and SHA-256 checksum in `vars.yml`. The archive is kept under
`/opt/drivion/uv/<version>/`. Installation does not change shell profiles or
download a separate Python interpreter. The Pi must use a 64-bit ARM OS.
It then syncs the car folder and creates the configured environment, currently
`~/car/system/env/drivion`, from OS Python with system package access. Build
headers, a compiler, and libgomp are installed for evdev and numerical packages.
The frozen `car/system/uv.lock` supplies the Python dependencies. Downloads and
builds are limited to reduce memory usage on the Pi. All requested runtime
imports, Picamera2, and the executable `drive.py` launcher are verified.

Change the environment name and matching relative path in `car/config.toml`.
Sync excludes `system/env/`, preserving the installed environment on the Pi.
Ansible verifies an existing environment uses OS Python and system packages;
if this verification fails, remove or rename that environment and provision again.

The reboot status reports `/var/run/reboot-required` if present. Its absence is
not a guarantee that no reboot would be useful after a kernel update.

`--syntax-check` validates without connecting. `--check` connects and previews
changes without applying package updates; its results reflect the available apt
cache. Future maintenance steps can extend this playbook or add new playbooks.

In check mode, package installation is previewed. uv installation is reported
without downloading or extracting the archive; import and runtime verification
run only during a real application.
