"""Identify and freeze the car files deployed by a development sync."""

import fnmatch
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

INFO_PATH = "system/info.toml"


def snapshot_car(source, destination, excludes):
    def ignore(directory, names):
        relative = Path(directory).relative_to(source)
        return [
            name
            for name in names
            if (relative / name).as_posix() == INFO_PATH
            or any(
                (relative / name).as_posix() == pattern.strip("/")
                for pattern in excludes
                if pattern.startswith("/")
            )
            or any(fnmatch.fnmatch(name, pattern.rstrip("/")) for pattern in excludes)
        ]

    shutil.copytree(source, destination, symlinks=True, ignore=ignore)


def snapshot_checksum(root):
    """Hash snapshot identity, streaming file contents with bounded memory."""
    digest = hashlib.sha256()
    for path in sorted(Path(root).rglob("*")):
        if not path.is_symlink() and not path.is_file():
            continue
        name = path.relative_to(root).as_posix().encode()
        kind = b"link" if path.is_symlink() else b"file"
        mode = b"" if path.is_symlink() else str(path.stat().st_mode & 0o111).encode()
        for value in (name, kind, mode):
            digest.update(len(value).to_bytes(8, "big"))
            digest.update(value)
        if path.is_symlink():
            content = os.readlink(path).encode()
            digest.update(len(content).to_bytes(8, "big"))
            digest.update(content)
        else:
            with path.open("rb") as stream:
                digest.update(os.fstat(stream.fileno()).st_size.to_bytes(8, "big"))
                # Continue the same digest to preserve existing deployment checksums.
                hashlib.file_digest(stream, lambda: digest)
    return digest.hexdigest()


def git_version(repository):
    def git(*arguments):
        return subprocess.run(
            ["git", *arguments],
            cwd=repository,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

    return {
        "version": git("describe", "--tags", "--match", "v[0-9]*", "--always"),
        "commit": git("rev-parse", "HEAD"),
        "dirty": bool(git("status", "--porcelain", "--untracked-files=normal")),
    }


def software_toml(record):
    lines = ["# Generated software deployment information; do not edit.", "[software]"]
    for key, value in record.items():
        encoded = str(value).lower() if isinstance(value, bool) else json.dumps(value)
        lines.append(f"{key} = {encoded}")
    return "\n".join(lines) + "\n"


# Executed on the Pi via SSH. The deployed utility performs the atomic update.
PUBLISH_SCRIPT = """import os, pathlib, subprocess, sys, tempfile
root = pathlib.Path(sys.argv[1])
system = root / "system"
if root.is_symlink() or system.is_symlink():
    raise ValueError("System information destination must not be a symlink")
# Initialize only a missing configuration. Existing Pi settings survive sync.
config = root / "config.toml"
defaults = root / "config.defaults.toml"
if config.is_symlink() or defaults.is_symlink():
    raise ValueError("Configuration must not be a symlink")
if not config.exists() and defaults.is_file():
    # Publish a separate complete copy without overwriting concurrent setup.
    with tempfile.NamedTemporaryFile(dir=root, delete=False) as stream:
        temporary = pathlib.Path(stream.name)
        stream.write(defaults.read_bytes())
    try:
        temporary.chmod(0o644)
        try:
            os.link(temporary, config)
        except FileExistsError:
            pass
    finally:
        temporary.unlink()

environment = os.environ.copy()
environment["PYTHONPATH"] = str(root)
subprocess.run(
    [sys.executable, "-m", "system.information.update", "--car-root", str(root),
     "--software-stdin", "--print"], input=sys.stdin.read(), text=True,
    env=environment, check=True)
"""
