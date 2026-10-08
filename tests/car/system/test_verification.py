"""Verify configuration-driven dependency selection and failure reporting."""

import subprocess
from unittest.mock import patch

import pytest

from car.system import verify_environment as verification
from car.system.provisioning import system_settings


def configure(root, dependencies, mappings=""):
    (root / "system").mkdir(exist_ok=True)
    (root / "config.toml").write_text(
        '[system]\npackages=["python3-picamera2"]\nsystem_imports=["libcamera"]\n'
    )
    (root / "system/pyproject.toml").write_text(
        "[project]\ndependencies=["
        + ",".join(repr(value) for value in dependencies)
        + "]\n"
        "[tool.drivion.verification.imports]\n" + mappings
    )


def test_dependency_changes_and_markers_drive_verification(tmp_path):
    configure(
        tmp_path,
        [
            "sample-package>=2",
            "opencv-python-headless",
            "skipped; python_version<'3.0'",
        ],
        'opencv-python-headless="cv2"\n',
    )
    plan = verification.verification_plan(tmp_path)
    assert [module for _, module in plan] == ["sample_package", "cv2", "libcamera"]
    configure(tmp_path, ["new-package"])
    assert [module for _, module in verification.verification_plan(tmp_path)] == [
        "new_package",
        "libcamera",
    ]


@pytest.mark.parametrize("mapping", ['removed="module"', 'sample="invalid/module"'])
def test_stale_or_invalid_mapping_rejected(tmp_path, mapping):
    configure(tmp_path, ["sample"], mapping)
    with pytest.raises(ValueError):
        verification.verification_plan(tmp_path)


def test_missing_distribution_wrong_version_and_import_failure(tmp_path):
    configure(tmp_path, ["missing", "wrong>=2", "broken"])

    def version(name):
        if name == "missing":
            raise verification.importlib.metadata.PackageNotFoundError(name)
        return "1.0"

    def execute(command, **kwargs):
        if "broken" in command[-1]:
            raise subprocess.CalledProcessError(1, command)
        return subprocess.CompletedProcess(command, 0)

    with (
        patch.object(verification.importlib.metadata, "version", side_effect=version),
        patch.object(verification.subprocess, "run", side_effect=execute) as run,
    ):
        assert verification.verify(tmp_path) == 1
    assert run.call_count == 2  # A failed import does not prevent the system check.


def test_successful_verification(tmp_path):
    configure(tmp_path, ["sample>=1"])
    with (
        patch.object(verification.importlib.metadata, "version", return_value="1.0"),
        patch.object(verification.subprocess, "run") as run,
    ):
        assert verification.verify(tmp_path) == 0
    assert run.call_count == 2


def test_invalid_system_package_rejected(tmp_path):
    (tmp_path / "config.toml").write_text(
        '[system]\npackages=["--bad"]\nsystem_imports=[]\n'
    )
    with pytest.raises(ValueError, match="packages"):
        system_settings(tmp_path)
