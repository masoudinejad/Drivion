#!/usr/bin/env python3
"""Mirror the local car folder to a Raspberry Pi using rsync over SSH."""

import argparse
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

if __package__:
    from . import versioning
else:
    import versioning
TOOLS_DIR = Path(__file__).resolve().parent
CAR_DIR = TOOLS_DIR.parents[1] / "car"
EXCLUDES = (
    ".venv/",
    "__pycache__/",
    "*.pyc",
    ".env",
    ".env.*",
    ".git/",
    ".pytest_cache/",
    ".ruff_cache/",
    ".ssh/",
    "/system/version.toml",
)


def read_settings(path):
    """Read literal KEY=value entries; never evaluate shell expressions."""
    settings = {}
    for number, line in enumerate(path.read_text().splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        key = key.strip()
        if not separator or not re.fullmatch(r"[A-Z_]+", key):
            raise ValueError(f"Invalid configuration entry on line {number}")
        value = value.strip()
        if value.startswith(("'", '"')):
            if len(value) < 2 or value[-1] != value[0]:
                raise ValueError(f"Unclosed quote on line {number}")
            value = value[1:-1]
        settings[key] = value
    return settings


def build_command(settings, dry_run=False, password=False, source=None):
    for key in ("PI_HOST", "PI_USER"):
        if not settings.get(key):
            raise ValueError(f"Set {key} in dev/sync/.env")
    host, user = settings["PI_HOST"], settings["PI_USER"]
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]*", host):
        raise ValueError("PI_HOST must be an IPv4 address or hostname")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", user):
        raise ValueError("PI_USER must be a Linux username")
    destination = settings.get("PI_CAR_PATH") or f"/home/{user}/car"
    destination = destination.rstrip("/")
    if destination != f"/home/{user}/car":
        raise ValueError("PI_CAR_PATH must be /home/<PI_USER>/car")
    # The path and username are validated because SSH runs remote commands via a shell.
    ssh = "ssh -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 -o NumberOfPasswordPrompts=1"
    if settings.get("SSH_AUTH_SOCK"):
        ssh += " -o IdentityAgent=SSH_AUTH_SOCK"
    if settings.get("PI_SSH_PUBLIC_KEY") and not password:
        key = public_key_path(settings["PI_SSH_PUBLIC_KEY"])
        ssh += " -o IdentitiesOnly=yes -i " + shlex.quote(str(key))
    command = ["rsync", "-rlptz", "--checksum", "--delete", "--itemize-changes"]
    if password:
        command = ["sshpass", "-e"] + command
    if dry_run:
        command.append("--dry-run")
    for pattern in EXCLUDES:
        command.extend(["--exclude", pattern])
    command.extend(
        [
            "-e",
            ssh,
            "--rsync-path",
            f"test ! -L /home/{user} && test ! -L {destination} && mkdir -p {destination} && rsync",
            str(source or CAR_DIR) + "/",
            f"{user}@{host}:{destination}/",
        ]
    )
    return command


def sync_versioned(settings, environment, dry_run=False, password=False):
    record = versioning.git_version(CAR_DIR.parent)
    with tempfile.TemporaryDirectory(prefix="drivion-car-") as directory:
        snapshot = Path(directory) / "car"
        versioning.snapshot_car(CAR_DIR, snapshot, EXCLUDES)
        record["checksum_sha256"] = versioning.snapshot_checksum(snapshot)
        command = build_command(settings, dry_run, password, snapshot)
        result = subprocess.run(command, env=environment, check=False)
        if result.returncode or dry_run:
            return result.returncode
        record["deployed_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        content = versioning.version_toml(record)
        ssh = shlex.split(command[command.index("--rsync-path") - 1])
        destination = settings.get("PI_CAR_PATH") or f"/home/{settings['PI_USER']}/car"
        ssh.extend(
            [
                f"{settings['PI_USER']}@{settings['PI_HOST']}",
                "python3 -c "
                + shlex.quote(versioning.PUBLISH_SCRIPT)
                + " "
                + shlex.quote(destination),
            ]
        )
        if password:
            ssh = ["sshpass", "-e"] + ssh
        result = subprocess.run(
            ssh, input=content, text=True, env=environment, check=False
        )
        if result.returncode:
            print(
                "Code transferred, but publishing the version record failed.",
                file=sys.stderr,
            )
            return result.returncode
        # Keep a local copy of the last successfully published deployment record.
        destination = CAR_DIR / versioning.VERSION_PATH
        destination.write_text(content)
        print(f"Deployed {record['version']} (dirty={record['dirty']})", flush=True)
        return 0


def public_key_path(value):
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = TOOLS_DIR / path
    path = path.resolve()
    if path.suffix != ".pub" or not path.is_file():
        raise ValueError("SSH public key must name an existing .pub file")
    return path


def build_key_command(settings, public_key=None):
    command = [
        "ssh-copy-id",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        "ConnectTimeout=10",
    ]
    public_key = public_key or settings.get("PI_SSH_PUBLIC_KEY")
    if public_key:
        public_key = public_key_path(public_key)
        # Agent-backed identities have no matching private-key file on disk.
        command.extend(["-f", "-i", str(public_key)])
    command.append(f"{settings['PI_USER']}@{settings['PI_HOST']}")
    return command


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview transfers and deletions without changing the Pi",
    )
    parser.add_argument(
        "--setup-ssh-key",
        action="store_true",
        help="Install an existing public key on the Pi using ssh-copy-id",
    )
    parser.add_argument(
        "--public-key",
        type=Path,
        help="Public .pub key to install (otherwise use ssh-copy-id's agent/default key selection)",
    )
    parser.add_argument(
        "--password",
        action="store_true",
        help="Use PI_PASSWORD through sshpass instead of normal SSH authentication",
    )
    args = parser.parse_args(argv)
    if args.public_key and not args.setup_ssh_key:
        parser.error("--public-key requires --setup-ssh-key")
    if args.dry_run and args.setup_ssh_key:
        parser.error("--dry-run cannot be combined with --setup-ssh-key")
    try:
        settings = read_settings(TOOLS_DIR / ".env")
        command = build_command(settings, args.dry_run, args.password)
        use_password = args.password or (
            args.setup_ssh_key and bool(settings.get("PI_PASSWORD"))
        )
        if use_password and not settings.get("PI_PASSWORD"):
            raise ValueError("Set PI_PASSWORD in dev/sync/.env to use --password")
        if args.setup_ssh_key:
            command = build_key_command(settings, args.public_key)
            if use_password:
                command = ["sshpass", "-e"] + command
        required = ["ssh", "ssh-copy-id" if args.setup_ssh_key else "rsync"]
        if not args.setup_ssh_key:
            required.append("git")
        if use_password:
            required.append("sshpass")
        for executable in required:
            if shutil.which(executable) is None:
                raise ValueError(
                    f"Install {executable} on the local machine before syncing"
                )
        if not CAR_DIR.is_dir():
            raise ValueError(f"Car source folder does not exist: {CAR_DIR}")
        environment = os.environ.copy()
        if settings.get("SSH_AUTH_SOCK"):
            environment["SSH_AUTH_SOCK"] = str(
                Path(settings["SSH_AUTH_SOCK"]).expanduser()
            )
        if use_password:
            environment["SSHPASS"] = settings["PI_PASSWORD"]
        message = (
            "Installing existing SSH public key..."
            if args.setup_ssh_key
            else ("Previewing car sync..." if args.dry_run else "Syncing car folder...")
        )
        print(message, flush=True)
        if args.setup_ssh_key:
            status = subprocess.run(command, env=environment, check=False).returncode
        else:
            status = sync_versioned(settings, environment, args.dry_run, args.password)
        if status:
            print(f"Command failed (exit code {status}).", file=sys.stderr)
        return status
    except FileNotFoundError:
        print(
            "Create dev/sync/.env from .env.example and fill in the Pi connection settings.",
            file=sys.stderr,
        )
        return 1
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f"Sync error: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
