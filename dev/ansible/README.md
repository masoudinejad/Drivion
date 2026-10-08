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

System packages are declared in `car/system/pyproject.toml` under
`tool.drivion.provisioning.packages`.
The runner reads and validates this list before creating the Ansible inventory.
Optional desktop recommendations are disabled; apt installs required dependencies.
System camera imports are declared in the same file under
`tool.drivion.provisioning.system_imports` and verified
inside the configured environment with access to system packages.

It installs uv and uvx into `/usr/local/bin`, using the pinned official ARM64
archive and SHA-256 checksum in `vars.yml`. The archive is kept under
`/opt/drivion/uv/<version>/`. Installation does not change shell profiles or
download a separate Python interpreter. The Pi must use a 64-bit ARM OS.
It then syncs the car folder and creates the configured environment, currently
`~/car/system/env/drivion`, from OS Python with system package access. Build
headers, a compiler, and libgomp are installed for evdev and numerical packages.
The frozen `car/system/uv.lock` supplies the Python dependencies. Downloads and
builds are limited to reduce memory usage on the Pi. All requested runtime
imports, system camera imports, and the executable `drive.py` launcher are verified.
`uv pip check` verifies dependency consistency.

`car/system/verify_environment.py` reads the dependency list directly from
`car/system/pyproject.toml`. It checks installed versions and imports each package
in a separate process. Import names default to distribution names with hyphens
replaced by underscores. Only exceptions belong in
`tool.drivion.verification.imports` in that same TOML file, for example
`opencv-python-headless = "cv2"`. Stale mappings fail validation. Dependencies
with inactive Python/platform markers are skipped. Ansible contains no repeated
Python package or import list.

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
