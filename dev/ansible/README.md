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

The same playbook configures a fallback Wi-Fi hotspot. Its non-secret settings
come only from `system.network` in `car/config.toml`. Set
`PI_HOTSPOT_PASSWORD` in `dev/sync/.env`, or leave it empty to reuse
`PI_PASSWORD`. The selected password must contain 8-63 printable ASCII
characters. It is passed through the Ansible process environment and hidden
from task output.

At boot, NetworkManager first tries saved Wi-Fi profiles normally. After 60
seconds, `drivion-wifi-fallback.timer` starts the hotspot only if `wlan0` still
has no active connection. The SSID is `Drivion-` followed by the final six
characters of the Raspberry Pi serial number. Its local address is always
`10.42.0.1`; it provides local access and does not require an internet uplink.
The hotspot never autoconnects on its own, so every reboot retries saved Wi-Fi
networks before falling back.

Raspberry Pi OS must have its WLAN country configured, as it does for normal
Wi-Fi client use. Set it during imaging or with `raspi-config`; the playbook does
not guess a regulatory country.

Because every hotspot uses the same IP address but each Pi has its own SSH host
key, identify the key by the visible SSID when connecting. For example:

```sh
ssh -o HostKeyAlias=Drivion-A4F29C driver@10.42.0.1
```

Using only `driver@10.42.0.1` for multiple cars causes an expected SSH host-key
mismatch warning. Do not disable SSH host-key checking to suppress it.

`drivion-system-info.service` runs on every boot before the fallback check. It
refreshes `~/car/system/info.toml` and the hotspot SSID from the current Pi. If
the SD card moves to another Pi, the model, serial number, and SSID therefore
change on the next boot while the software deployment information is retained.

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

It installs uv and uvx through uv's official standalone installer. Existing
archive-style installations are migrated once so managed self-updates are
available. Later runs use `uv self update --dry-run` and update only when a newer
stable release exists; an up-to-date installation is unchanged. The installer
URL and executable directory live under `tool.drivion.uv` in
`car/system/pyproject.toml`. Installation does not change shell profiles or
download a separate Python interpreter. The Pi must use a 64-bit ARM OS.

Arduino provisioning runs automatically during every normal setup run. To
install or repair only Arduino tooling without running the package upgrades,
network setup, or Python environment tasks, use:

```sh
uv run --project dev python dev/ansible/run.py --arduino-only
```

This uses the same TOML settings and idempotent tasks as full provisioning,
including CLI version, sketchbook, and AVR core verification. A sync alone
copies code and does not install system tools. Check mode previews installation.

It also installs the configured Arduino CLI ARM64 release, grants the car user
the configured serial-device group, and installs the configured AVR core. Each
sketch should be placed in its own folder under the configured sketchbook. A new
login is required before an existing shell gains the new group membership.
The sketchbook and selected device address are the only Arduino settings in
`car/config.toml`. Versions, checksums, URLs, groups, core identifiers, protected
paths, and timeouts are provisioning metadata under `tool.drivion.arduino` in
`car/system/pyproject.toml`; the runner validates and passes them to Ansible.

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

System paths, apt lock timing, uv concurrency, and numerical-library thread
limits are also declared under `tool.drivion` in `car/system/pyproject.toml`.
Ansible consumes validated inventory values instead of embedding those settings
in tasks.

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

The playbook entry point is `update.yml`. Reusable operations are grouped under
`tasks/`, while service and application templates are grouped by domain under
`templates/`.
