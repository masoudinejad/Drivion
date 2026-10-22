"""The startup screen renders the central report without probing devices."""

from car.system.ui.startup import show_startup


def report():
    result = {
        name: {"status": "ok"}
        for name in (
            "configuration",
            "environment",
            "hardware",
            "arduino",
            "network",
            "joystick",
        )
    }
    result["camera"] = {
        "status": "ok",
        "devices": [{"index": 0, "id": "/base/camera", "model": "imx219"}],
    }
    return result


def test_startup_reports_central_snapshot(capsys, caplog):
    with caplog.at_level("INFO"):
        show_startup(report())
    output = capsys.readouterr().out
    assert "Camera 0: model=imx219 id=/base/camera" in output
    assert "id=/base/camera" in caplog.text
    assert "Configuration: ok" in output
    assert "Environment: ok" in output
    assert "Saved results from system/info.toml" in output


def test_startup_reports_failed_evaluations(capsys):
    snapshot = report()
    snapshot["camera"] = {"status": "error", "error": "picamera2 unavailable"}
    show_startup(snapshot)
    output = capsys.readouterr().out
    assert "[warning] Camera: error" in output
    assert "picamera2 unavailable" in output
    assert "Camera 0:" not in output


def test_display_preview_does_not_claim_checks_passed(capsys):
    show_startup()
    output = capsys.readouterr().out
    assert "No saved system evaluation available" in output
    assert "Configuration: ok" not in output
