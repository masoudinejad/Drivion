# Development tools

Sync utilities live in `sync/`; formatting tools live in `quality/`.
Tests live separately in the repository-level `tests/` folder.

Raspberry Pi maintenance automation lives in `ansible/`. See the
[Ansible instructions](ansible/README.md) for updates and upgrades using the
existing local connection settings.

Development and debugging utilities live here, with independent uv dependencies.

## Sync the car code to a Raspberry Pi

The local machine needs Python 3.11+, SSH, and rsync. Key setup also uses
ssh-copy-id. Password automation additionally requires sshpass. The Pi needs SSH
enabled and rsync installed (`sudo apt install rsync`). Initial key setup needs
a working login method, usually password authentication.

Copy `sync/.env.example` to `sync/.env` and fill in `PI_HOST` and
`PI_USER`. `PI_PASSWORD` is optional for normal key-based sync. `PI_CAR_PATH`
defaults to `/home/driver/car` with `PI_USER=driver`. Local `car/drive.py`
becomes `/home/driver/car/drive.py`. The destination is restricted to
`/home/<PI_USER>/car`; the home and destination folders must not be symlinks.

The `.env` file is ignored by Git. Restrict its permissions with `chmod 600
dev/sync/.env`. Passwords are literal values; quote them if they have leading
or trailing spaces. They are passed to sshpass through its environment, never
command arguments.

From the repository root:

```sh
./dev/sync/sync_car.py --dry-run
./dev/sync/sync_car.py
```

The script also works from other directories. It uses only Python's standard
library, so environment activation is unnecessary. Alternatively, run `uv run
--project dev dev/sync/sync_car.py` from the repository root.

Only `car/` is transferred. Changed files and deletions are shown, executable
permissions are preserved, and missing destination directories are created.
Virtual environments, Python caches, Git metadata, `.ssh`, and `.env` files are
excluded and preserved on the Pi. `car/config.toml` is mirrored, so local
settings replace the remote copy. Runtime data folders should be added to the
exclusions when their locations are defined.

The Pi also needs Python 3 to publish the generated `system/info.toml` record
after a successful transfer. The record combines deployment data with current
hardware and system information. Sync uses a frozen local snapshot and content
checksums. Dry runs and key setup do not publish a record. See
[version tracking](../docs/versioning.md) for release tags and record fields.

New SSH host keys are accepted and saved; changed keys are rejected. Sync does
not restart the car, install dependencies, or flash the Arduino. A dry run does
not transfer or delete files, but may create the destination directory and save
a new SSH host key.

Rsync mirrors deletions inside the dedicated `car/` destination. Excluded files
and directories are preserved. Other home-directory contents are outside the
sync. Unexcluded files created only inside the destination will be removed on
the next sync.

## Use your existing SSH key

Normal sync uses your standard SSH configuration and agent, including keys
unlocked through an external authentication tool. It does not generate keys or
read private key contents.

For pass-cli, run `pass-cli ssh-agent daemon status` to find its socket. Set
`SSH_AUTH_SOCK` in the local `.env` to that socket path if this process does not
inherit it. The pass-cli daemon must be running for key authentication.

Set `PI_SSH_PUBLIC_KEY` to an exported `.pub` file to select a specific agent
identity. Relative paths are resolved from `dev/sync/`. Normal sync then uses
`IdentitiesOnly=yes`; key setup installs only this public key. Private keys
remain in the agent. Local public-key files can be kept in the Git-ignored
`dev/sync/.ssh/` directory.

Install an existing public key once:

```sh
./dev/sync/sync_car.py --setup-ssh-key
# Or select an exported public key explicitly:
./dev/sync/sync_car.py --setup-ssh-key --public-key ~/.ssh/id_ed25519.pub
```

Without a selected public key, ssh-copy-id selects keys from your SSH agent or
its default public key file and skips duplicates. Explicit public-key selection
uses ssh-copy-id's forced public-only installation mode because the private key
stays in the agent; run that setup once to avoid duplicate entries. Existing
authorized keys are preserved. Authenticate/unlock your agent before running
these commands. If `PI_PASSWORD` is configured, setup uses sshpass; otherwise it
prompts through SSH. Keep `PI_PASSWORD` empty to use your normal interactive
login for setup.

Then run the usual sync command. No Pi password in `.env` is required. To
explicitly use the stored Pi password instead, run `./dev/sync/sync_car.py
--password`. Key setup only installs the public key; it does not also sync code.

## Formatting and commit checks

Install the development tools and Git hook from the repository root:

```sh
uv sync --project dev
npm ci --prefix dev
uv run --project dev pre-commit install
```

Every commit runs formatting and linting across all tracked and non-ignored
project source files, including files outside the staged changes. Ruff applies
safe default lint fixes and formats Python; markdownlint applies supported
fixes; clang-format formats C/C++ and Arduino `.ino` files using its default
LLVM style. No custom formatting or lint rules are configured. Review and stage
any edits made by the hook before retrying the commit. Remaining lint errors
block commits.

Run the same checks manually:

```sh
uv run --project dev python dev/quality/format_all.py
uv run --project dev python dev/quality/format_all.py --check
```

The `--check` option does not edit files. Markdown line wrapping and other
issues without automatic fixes need manual corrections. Tool versions are locked
in `uv.lock` and `package-lock.json`; other developers need to install the hook
in their own checkout.

## Tests

Run all tests from the repository root:

```sh
uv run --project dev pytest
```

Pytest discovers the suite under `tests/`. Run a subset with
`uv run --project dev pytest tests/dev` or
`uv run --project dev pytest tests/car/system`.
See [test instructions](../tests/README.md) for requirements.
