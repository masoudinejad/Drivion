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
    """Hash sorted paths, contents/link targets, and executable permission bits."""
    digest = hashlib.sha256()
    for path in sorted(Path(root).rglob("*")):
        if not path.is_symlink() and not path.is_file():
            continue
        name = path.relative_to(root).as_posix().encode()
        content = os.readlink(path).encode() if path.is_symlink() else path.read_bytes()
        kind = b"link" if path.is_symlink() else b"file"
        mode = b"" if path.is_symlink() else str(path.stat().st_mode & 0o111).encode()
        for value in (name, kind, mode, content):
            digest.update(len(value).to_bytes(8, "big"))
            digest.update(value)
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
PUBLISH_SCRIPT = """import os, pathlib, subprocess, sys
root = pathlib.Path(sys.argv[1])
system = root / "system"
if root.is_symlink() or system.is_symlink():
    raise ValueError("System information destination must not be a symlink")
environment = os.environ.copy()
environment["PYTHONPATH"] = str(root)
subprocess.run(
    [sys.executable, "-m", "system.information.update", "--car-root", str(root),
     "--software-stdin", "--print"], input=sys.stdin.read(), text=True,
    env=environment, check=True)
"""
