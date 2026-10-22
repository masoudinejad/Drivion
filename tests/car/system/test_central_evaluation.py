"""Exercise evaluation isolation, persisted failures and privilege boundaries."""

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import tomllib

from car.system.information import runtime, update


@pytest.fixture
def root(tmp_path):
    import shutil

    source = Path(__file__).resolve().parents[3] / "car"
    root = tmp_path / "car"
    (root / "system").mkdir(parents=True)
    shutil.copy(source / "config.toml", root / "config.toml")
    shutil.copy(source / "system/pyproject.toml", root / "system/pyproject.toml")
    return root


def runtime_result():
    return {
        "configuration": {"status": "ok"},
        "environment": {"status": "ok", "dependencies": []},
        "camera": {"status": "missing", "devices": []},
        "joystick": {"status": "unconfigured", "devices": []},
    }


def test_partial_evaluation_replaces_stale_devices_and_keeps_deployment(root):
    path = root / update.INFO_PATH
    update.publish(
        path,
        {
            "software": {"commit": "abc"},
            "camera": {"status": "ok", "devices": [{"id": "old"}]},
        },
    )
    with (
        patch.object(
            update, "hardware_info", side_effect=RuntimeError("no device tree")
        ),
        patch.object(update, "discover", side_effect=OSError("Arduino unavailable")),
        patch.object(update, "runtime_info", return_value=runtime_result()) as worker,
    ):
        result = update.refresh_info(root)
    stored = tomllib.loads(path.read_text())
    assert stored == result
    assert stored["software"] == {"commit": "abc"}
    assert stored["hardware"]["status"] == "error"
    assert stored["arduino"]["error"] == "Arduino unavailable"
    assert stored["camera"] == {"status": "missing", "devices": []}
    assert stored["checks"]["status"] == "error"
    assert stored["checks"]["checked_at"]
    worker.assert_called_once_with(root, root)


def test_missing_environment_is_recorded_instead_of_aborting(root):
    result = update.runtime_info(root, root)
    assert all(value["status"] == "error" for value in result.values())
    assert "environment is missing" in result["environment"]["error"]


def test_root_worker_drops_privileges_before_running_user_python(root):
    python = root / "system/env/drivion/bin/python"
    python.parent.mkdir(parents=True)
    python.touch()
    owner = SimpleNamespace(
        pw_uid=1000, pw_gid=1000, pw_name="driver", pw_dir="/home/driver"
    )
    process = MagicMock()
    process.returncode = 0
    process.communicate.return_value = (json.dumps(runtime_result()), "")
    with (
        patch.object(os, "geteuid", return_value=0),
        patch.object(update.pwd, "getpwuid", return_value=owner),
        patch.object(os, "getgrouplist", return_value=[1000, 44]),
        patch.object(update.subprocess, "Popen") as execute,
    ):
        execute.return_value.__enter__.return_value = process
        assert update.runtime_info(root, root) == runtime_result()
    options = execute.call_args.kwargs
    assert options["user"] == 1000
    assert options["group"] == 1000
    assert options["extra_groups"] == [1000, 44]
    assert options["env"]["HOME"] == "/home/driver"
    assert options["env"]["PYTHONPATH"] == str(root)
    assert options["start_new_session"] is True
    process.communicate.assert_called_once_with(timeout=900)


def test_worker_timeout_kills_entire_group_and_records_failure(root):
    python = root / "system/env/drivion/bin/python"
    python.parent.mkdir(parents=True)
    python.touch()
    process = MagicMock(pid=1234)
    process.communicate.side_effect = [
        update.subprocess.TimeoutExpired("worker", 900),
        ("", ""),
    ]
    with (
        patch.object(os, "geteuid", return_value=1000),
        patch.object(update.subprocess, "Popen") as execute,
        patch.object(os, "killpg") as kill,
    ):
        execute.return_value.__enter__.return_value = process
        result = update.runtime_info(root, root)
    kill.assert_called_once_with(1234, update.signal.SIGKILL)
    assert "exceeded 900 seconds" in result["environment"]["error"]


def test_runtime_records_camera_even_when_config_and_dependencies_fail(
    root, monkeypatch
):
    from car.src import config
    from car.src.joystick import discovery
    from car.system import environment, verify_environment

    monkeypatch.setattr(
        config, "load_config", MagicMock(side_effect=ValueError("bad config"))
    )
    monkeypatch.setattr(environment, "environment_path", lambda root: Path(sys.prefix))
    monkeypatch.setattr(
        verify_environment,
        "dependency_report",
        lambda root: [
            {
                "requirement": "broken",
                "module": "broken",
                "status": "error",
                "error": "missing",
            }
        ],
    )
    monkeypatch.setattr(discovery, "discover", lambda: ([], []))
    monkeypatch.setitem(
        sys.modules,
        "picamera2",
        SimpleNamespace(
            Picamera2=SimpleNamespace(
                global_camera_info=lambda: [
                    {"Id": "/base/camera", "Model": "imx219", "Rotation": 180}
                ]
            )
        ),
    )
    result = runtime.evaluate(root)
    assert result["configuration"]["error"] == "bad config"
    assert result["environment"]["status"] == "error"
    assert result["camera"]["devices"] == [
        {"id": "/base/camera", "model": "imx219", "index": 0, "rotation": 180}
    ]
    assert result["joystick"]["status"] == "error"


def test_update_cli_publishes_one_snapshot(root, capsys):
    tree = root / "device-tree"
    tree.mkdir()
    (tree / "model").write_text("Pi")
    (tree / "serial-number").write_text("000000123456")
    with (
        patch.object(update, "runtime_info", return_value=runtime_result()) as worker,
        patch.object(update, "discover", return_value={"status": "ok", "ports": []}),
    ):
        assert (
            update.main(
                ["--car-root", str(root), "--device-tree", str(tree), "--print"]
            )
            == 0
        )
    assert tomllib.loads(capsys.readouterr().out) == tomllib.loads(
        (root / update.INFO_PATH).read_text()
    )
    worker.assert_called_once()


def test_launcher_missing_environment_does_not_change_boot_report(root):
    import shutil
    import subprocess

    source = Path(__file__).resolve().parents[3] / "car"
    shutil.copy(source / "drive.py", root / "drive.py")
    for name in ("__init__.py", "environment.py", "configuration.py"):
        shutil.copy(source / "system" / name, root / "system" / name)
    for name in ("information", "arduino", "ui"):
        shutil.copytree(
            source / "system" / name,
            root / "system" / name,
            ignore=shutil.ignore_patterns("__pycache__"),
        )
    path = root / update.INFO_PATH
    original = '[checks]\nstatus="ok"\nchecked_at="boot-time"\n'
    path.write_text(original)
    result = subprocess.run(
        [sys.executable, str(root / "drive.py")],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 1
    assert path.read_text() == original
    assert "environment is missing" in result.stderr


def test_deployment_update_preserves_results_and_does_not_probe(root):
    original = {
        "checks": {"checked_at": "boot-time", "evaluated_commit": "old"},
        "camera": {"status": "ok", "devices": [{"id": "/base/camera"}]},
    }
    update.publish(root / update.INFO_PATH, original)
    with patch.object(
        update, "collect_info", side_effect=AssertionError("No sync probes")
    ):
        result = update.publish_deployment(root, {"commit": "new"})
    assert result == {**original, "software": {"commit": "new"}}
    assert tomllib.loads((root / update.INFO_PATH).read_text()) == result


def test_explicit_evaluation_can_fail_provisioning_after_saving_report(root):
    report = {"configuration": {"status": "ok"}, "environment": {"status": "error"}}
    with patch.object(update, "refresh_info", return_value=report) as refresh:
        assert update.main(["--car-root", str(root), "--require-runtime"]) == 1
    refresh.assert_called_once()
