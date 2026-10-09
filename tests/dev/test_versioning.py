"""Checks for reproducible snapshots and success-only deployment records."""

import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

import tomllib

from dev.sync import sync_car, versioning


def test_snapshot_excludes_generated_files_and_freezes_content(tmp_path):
    source = tmp_path / "source"
    (source / "system/.venv").mkdir(parents=True)
    (source / "system/env/drivion").mkdir(parents=True)
    (source / "system/env/drivion/package.py").write_text("environment")
    (source / "system/info.toml").write_text("old deployment")
    (source / "system/.venv/package.py").write_text("environment")
    (source / ".env").write_text("secret")
    (source / "drive.py").write_text("original")
    snapshot = tmp_path / "snapshot"
    versioning.snapshot_car(source, snapshot, sync_car.EXCLUDES)
    checksum = versioning.snapshot_checksum(snapshot)
    (source / "drive.py").write_text("changed")
    assert (snapshot / "drive.py").read_text() == "original"
    assert not (snapshot / "system/info.toml").exists()
    assert not (snapshot / "system/.venv").exists()
    assert not (snapshot / "system/env").exists()
    assert not (snapshot / ".env").exists()
    assert versioning.snapshot_checksum(snapshot) == checksum
    (snapshot / "drive.py").chmod(0o755)
    assert versioning.snapshot_checksum(snapshot) != checksum


def test_git_release_and_dirty_state(tmp_path):
    def git(*args):
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

    git("init")
    git("config", "user.name", "Test")
    git("config", "user.email", "test@example.com")
    (tmp_path / "code.py").write_text("original")
    git("add", "code.py")
    git("commit", "-m", "Initial test code")
    untagged = versioning.git_version(tmp_path)
    assert untagged["version"] == untagged["commit"][:7]
    assert not untagged["dirty"]
    git("tag", "v0.1.0")
    assert versioning.git_version(tmp_path)["version"] == "v0.1.0"
    (tmp_path / "code.py").write_text("changed")
    assert versioning.git_version(tmp_path)["dirty"]


def test_publish_is_atomic_and_collects_system_info(tmp_path):
    (tmp_path / "system").mkdir()
    source = Path(versioning.__file__).parents[2] / "car"
    shutil.copy(source / "config.toml", tmp_path / "config.toml")
    shutil.copy(source / "system/__init__.py", tmp_path / "system/__init__.py")
    shutil.copy(
        source / "system/configuration.py", tmp_path / "system/configuration.py"
    )
    shutil.copy(source / "system/pyproject.toml", tmp_path / "system/pyproject.toml")
    shutil.copytree(source / "system/information", tmp_path / "system/information")
    shutil.copytree(source / "system/arduino", tmp_path / "system/arduino")
    device_tree = tmp_path / "device-tree"
    device_tree.mkdir()
    (device_tree / "model").write_bytes(b"Raspberry Pi Test\0")
    (device_tree / "serial-number").write_bytes(b"00000000a4f29c\0")
    record = {"version": "v0.1.0", "commit": "abc", "dirty": True}
    content = versioning.software_toml(record)
    script = versioning.PUBLISH_SCRIPT.replace(
        '"--software-stdin", "--print"',
        f'"--software-stdin", "--device-tree", {str(device_tree)!r}, "--print"',
    )
    subprocess.run(
        ["python3", "-c", script, str(tmp_path)],
        input=content,
        text=True,
        check=True,
    )
    info = tomllib.loads((tmp_path / "system/info.toml").read_text())
    assert info["software"] == record
    assert info["hardware"] == {
        "model": "Raspberry Pi Test",
        "serial_number": "00000000a4f29c",
    }


def test_failed_sync_and_dry_run_do_not_publish(tmp_path):
    car = tmp_path / "car"
    (car / "system").mkdir(parents=True)
    (car / "system/info.toml").write_text("last deployment")
    (car / "drive.py").write_text("new")
    settings = {"PI_HOST": "pi.local", "PI_USER": "driver"}
    record = {"version": "abc", "commit": "abc", "dirty": True}
    for dry_run, status in [(False, 23), (True, 0)]:
        with (
            patch.object(sync_car, "CAR_DIR", car),
            patch.object(versioning, "git_version", return_value=record.copy()),
            patch.object(
                sync_car.subprocess,
                "run",
                return_value=subprocess.CompletedProcess([], status),
            ) as run,
        ):
            assert sync_car.sync_versioned(settings, {}, dry_run) == status
            assert run.call_count == 1
        assert (car / "system/info.toml").read_text() == "last deployment"


def test_success_publishes_and_caches_record(tmp_path):
    car = tmp_path / "car"
    (car / "system").mkdir(parents=True)
    (car / "drive.py").write_text("code")
    source = Path(versioning.__file__).parents[2] / "car"
    shutil.copy(source / "system/pyproject.toml", car / "system/pyproject.toml")
    settings = {"PI_HOST": "pi.local", "PI_USER": "driver"}
    record = {"version": "abc", "commit": "abc", "dirty": True}
    with (
        patch.object(sync_car, "CAR_DIR", car),
        patch.object(versioning, "git_version", return_value=record),
        patch.object(sync_car.subprocess, "run") as run,
    ):
        run.side_effect = [
            subprocess.CompletedProcess([], 0),
            subprocess.CompletedProcess([], 0, stdout="[software]\nversion='abc'\n"),
        ]
        assert sync_car.sync_versioned(settings, {}) == 0
        assert run.call_count == 2
        sent = tomllib.loads(run.call_args.kwargs["input"])["software"]
    local = tomllib.loads((car / "system/info.toml").read_text())["software"]
    assert local == {"version": "abc"}
    assert len(sent["checksum_sha256"]) == 64
    assert "deployed_at" in sent
