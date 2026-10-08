"""Checks for reproducible snapshots and success-only deployment records."""

import subprocess
from unittest.mock import patch

import tomllib

from dev.sync import sync_car, versioning


def test_snapshot_excludes_generated_files_and_freezes_content(tmp_path):
    source = tmp_path / "source"
    (source / "system/.venv").mkdir(parents=True)
    (source / "system/env/drivion").mkdir(parents=True)
    (source / "system/env/drivion/package.py").write_text("environment")
    (source / "system/version.toml").write_text("old deployment")
    (source / "system/.venv/package.py").write_text("environment")
    (source / ".env").write_text("secret")
    (source / "drive.py").write_text("original")
    snapshot = tmp_path / "snapshot"
    versioning.snapshot_car(source, snapshot, sync_car.EXCLUDES)
    checksum = versioning.snapshot_checksum(snapshot)
    (source / "drive.py").write_text("changed")
    assert (snapshot / "drive.py").read_text() == "original"
    assert not (snapshot / "system/version.toml").exists()
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


def test_publish_is_atomic_and_valid_toml(tmp_path):
    (tmp_path / "system").mkdir()
    record = {"version": "v0.1.0", "commit": "abc", "dirty": True}
    content = versioning.version_toml(record)
    subprocess.run(
        ["python3", "-c", versioning.PUBLISH_SCRIPT, str(tmp_path)],
        input=content,
        text=True,
        check=True,
    )
    assert (
        tomllib.loads((tmp_path / "system/version.toml").read_text())["code"] == record
    )
    assert len(list((tmp_path / "system").iterdir())) == 1


def test_failed_sync_and_dry_run_do_not_publish(tmp_path):
    car = tmp_path / "car"
    (car / "system").mkdir(parents=True)
    (car / "system/version.toml").write_text("last deployment")
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
        assert (car / "system/version.toml").read_text() == "last deployment"


def test_success_publishes_and_caches_record(tmp_path):
    car = tmp_path / "car"
    (car / "system").mkdir(parents=True)
    (car / "drive.py").write_text("code")
    settings = {"PI_HOST": "pi.local", "PI_USER": "driver"}
    record = {"version": "abc", "commit": "abc", "dirty": True}
    with (
        patch.object(sync_car, "CAR_DIR", car),
        patch.object(versioning, "git_version", return_value=record),
        patch.object(
            sync_car.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)
        ) as run,
    ):
        assert sync_car.sync_versioned(settings, {}) == 0
        assert run.call_count == 2
        sent = tomllib.loads(run.call_args.kwargs["input"])["code"]
    local = tomllib.loads((car / "system/version.toml").read_text())["code"]
    assert sent == local
    assert len(local["checksum_sha256"]) == 64
    assert "deployed_at" in local
