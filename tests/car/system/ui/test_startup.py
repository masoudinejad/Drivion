"""Verify startup camera discovery reports identities and failures accurately."""

import pytest

from car.src.camera import camera
from car.system.ui.startup import show_startup


def test_startup_reports_camera_identity(monkeypatch, capsys, caplog):
    monkeypatch.setattr(
        camera, "camera_inventory", lambda: [{"Id": "/base/camera", "Model": "imx219"}]
    )
    with caplog.at_level("INFO"):
        show_startup()
    assert "Camera 0 detected: model=imx219 id=/base/camera" in capsys.readouterr().out
    assert "id=/base/camera" in caplog.text


@pytest.mark.parametrize("failure", [None, ImportError("picamera2 unavailable")])
def test_startup_reports_failed_detection(monkeypatch, capsys, failure):
    def inventory():
        if failure:
            raise failure
        return []

    monkeypatch.setattr(camera, "camera_inventory", inventory)
    show_startup()
    output = capsys.readouterr().out
    assert "[warning] Camera detection failed:" in output
    assert "Camera 0 detected" not in output
