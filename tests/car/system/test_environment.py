"""Validate configured environments and the executable bootstrap."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from car.system.environment import environment_path


def configure(root, name="drivion", path="system/env/drivion"):
    (root / "config.toml").write_text(
        f'[system.python_environment]\nname="{name}"\npath="{path}"\n'
    )


def test_configured_environment(tmp_path):
    configure(tmp_path)
    assert environment_path(tmp_path) == tmp_path / "system/env/drivion"


@pytest.mark.parametrize(
    "name,path",
    [
        ("../bad", "system/env/../bad"),
        ("drivion", "/tmp/env"),
        ("drivion", "system/env/other"),
    ],
)
def test_invalid_configuration(tmp_path, name, path):
    configure(tmp_path, name, path)
    with pytest.raises(ValueError):
        environment_path(tmp_path)


def test_missing_configuration(tmp_path):
    (tmp_path / "config.toml").write_text("")
    with pytest.raises(ValueError):
        environment_path(tmp_path)


def test_launcher_enters_environment_from_another_directory(tmp_path):
    root = tmp_path / "car"
    root.mkdir()
    configure(root)
    source = Path(__file__).resolve().parents[3] / "car"
    shutil.copy(source / "drive.py", root / "drive.py")
    shutil.copytree(
        source / "system",
        root / "system",
        ignore=shutil.ignore_patterns("env", ".venv", "__pycache__", "uv.lock"),
    )
    target = environment_path(root)
    subprocess.run(
        [sys.executable, "-m", "venv", "--without-pip", str(target)], check=True
    )
    launcher = root / "drive.py"
    launcher.write_text(
        launcher.read_text().replace(
            "def main():",
            "def main():\n    print(sys.prefix)\n    return",
        )
    )
    result = subprocess.run(
        [sys.executable, str(launcher)],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=True,
    )
    assert result.stdout.strip() == str(target)


def test_manage_executable_enters_environment_from_another_directory(tmp_path):
    root = tmp_path / "car"
    root.mkdir()
    configure(root)
    source = Path(__file__).resolve().parents[3] / "car/system"
    shutil.copytree(
        source,
        root / "system",
        ignore=shutil.ignore_patterns("env", "__pycache__", "uv.lock"),
    )
    target = environment_path(root)
    subprocess.run(
        [sys.executable, "-m", "venv", "--without-pip", str(target)], check=True
    )
    launcher = root / "system/manage.py"
    launcher.write_text(
        launcher.read_text().replace(
            "        run_management(CAR_ROOT)", "        print(sys.prefix)"
        )
    )
    result = subprocess.run(
        [str(launcher)], cwd=tmp_path, text=True, capture_output=True, check=True
    )
    assert result.stdout.strip() == str(target)
