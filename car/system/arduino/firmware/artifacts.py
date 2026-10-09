"""Validate immutable compile manifests and hash exported firmware outputs."""

import hashlib
from pathlib import Path

import tomllib

from ..settings import load_context, validate_flash_configuration
from .definitions import validate_fqbn
from .identity import validate_identity


def file_checksum(path):
    """Stream binaries rather than loading entire compiler outputs into memory."""
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def artifact_checksums(directory):
    """Hash all compiler outputs; reject links and empty/non-firmware output."""
    directory = Path(directory)
    if not directory.is_dir() or directory.is_symlink():
        raise ValueError("Missing compiled artifact directory")
    hashes = {}
    for path in sorted(directory.rglob("*")):
        if path.is_symlink():
            raise ValueError("Compiled artifacts must not be symlinks")
        if path.is_file():
            hashes[path.relative_to(directory).as_posix()] = file_checksum(path)
    if not any(Path(name).suffix in (".hex", ".bin") for name in hashes):
        raise ValueError("Build contains no compiled firmware")
    return hashes


def load_build(artifacts, root, *, context=None):
    """Read an immutable compile snapshot, never infer a version from live settings."""
    context = context or load_context(root)
    root = context.root
    settings = context.compile_settings
    directory = Path(artifacts)
    if directory.is_symlink():
        raise ValueError("Compiled build must not be a symlink")
    directory = directory.resolve(strict=True)
    builds = context.directory(settings["build_directory"])
    if (
        not builds.is_relative_to(root)
        or not directory.is_relative_to(builds)
        or directory.name != "artifacts"
    ):
        raise ValueError("Select the artifact directory returned by compile_firmware")
    manifest_path = directory.parent / settings["manifest_filename"]
    if manifest_path.is_symlink():
        raise ValueError("Build manifest must not be a symlink")
    with manifest_path.open("rb") as stream:
        manifest = tomllib.load(stream)
    if set(manifest) != {"firmware", "board", "serial", "artifacts"}:
        raise ValueError("Invalid or incomplete compile manifest; compile again")
    validate_identity(manifest["firmware"])
    if not isinstance(manifest["board"], dict) or set(manifest["board"]) != {"fqbn"}:
        raise ValueError("Build manifest must contain its target board")
    validate_fqbn(manifest["board"]["fqbn"])
    if not isinstance(manifest["serial"], dict) or set(manifest["serial"]) != {
        "baud_rate",
        "query_command",
    }:
        raise ValueError("Build manifest must contain its serial query contract")
    query_settings = {**context.flash_settings, **manifest["serial"]}
    validate_flash_configuration(query_settings)
    if artifact_checksums(directory) != manifest["artifacts"]:
        raise ValueError("Compiled artifacts changed since compilation; compile again")
    return directory, manifest, query_settings
