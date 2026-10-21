"""Exercise diagnostics without opening physical devices."""

import io
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from car.src.configuration.schema import HardwareTestsConfig
from car.system.management.hardware_tests import run_check


@pytest.fixture
def root(tmp_path):
    source = Path(__file__).resolve().parents[3] / "car/config.toml"
    config = (
        source.read_text()
        .replace("camera_frames = 30", "camera_frames = 2")
        .replace("arduino_samples = 10", "arduino_samples = 2")
        .replace("warmup_seconds = 1.0", "warmup_seconds = 0.0")
    )
    (tmp_path / "config.toml").write_text(config)
    (tmp_path / "system").mkdir()
    metadata = source.parent / "system/pyproject.toml"
    (tmp_path / "system/pyproject.toml").write_text(metadata.read_text())
    return tmp_path


def test_camera_records_latency_and_separate_logs(root):
    terminal = io.StringIO()
    camera = MagicMock()
    camera.single_capture.return_value = np.zeros((480, 640, 3), dtype=np.uint8)
    with patch("car.src.camera.camera.Camera") as factory:
        factory.return_value.__enter__.return_value = camera
        for _ in range(2):
            transcript = run_check(root, "camera", stream=terminal)
            assert "PASS" in transcript
            assert "Capture latency ms" in transcript
            assert "observed throughput" in transcript
        assert factory.return_value.__exit__.call_count == 2
    assert len(list(root.glob("system/hardware_tests/logs/*.log"))) == 2
    assert "capture latency=" in terminal.getvalue()


def test_camera_failure_is_logged_and_closed(root):
    with patch("car.src.camera.camera.Camera") as factory:
        factory.return_value.__enter__.return_value.single_capture.side_effect = (
            OSError("disconnected")
        )
        transcript = run_check(root, "camera", stream=io.StringIO())
        assert "FAIL" in transcript and "disconnected" in transcript
        factory.return_value.__exit__.assert_called_once()


def test_arduino_correlates_snapshots_and_records_latencies(root):
    from car.src.communication import ReportedValues

    client = MagicMock()
    client.status_stale = False
    client.request_values.side_effect = [4, 5]
    client.poll.side_effect = [
        [ReportedValues(0, None, None, 0.0, 3, 3)],
        [ReportedValues(0, None, None, 0.0, 4, 4)],
        [ReportedValues(0, None, None, 0.0, 5, 5)],
    ]
    with patch("car.src.communication.Communication.open") as opened:
        opened.return_value.__enter__.return_value = client
        transcript = run_check(root, "arduino", stream=io.StringIO())
        assert "PASS" in transcript
        assert "Handshake round-trip latency ms" in transcript
        assert "Telemetry round-trip latency ms" in transcript
        assert client.poll.call_count == 3
        client.set_target.assert_not_called()
        opened.return_value.__exit__.assert_called_once()


def test_arduino_timeout_is_logged(root):
    client = MagicMock()
    client.poll.return_value = []
    with (
        patch("car.src.communication.Communication.open") as opened,
        patch(
            "car.system.management.hardware_tests.time.monotonic",
            side_effect=range(100),
        ),
    ):
        opened.return_value.__enter__.return_value = client
        transcript = run_check(root, "arduino", stream=io.StringIO())
        assert "FAIL" in transcript and "timed out" in transcript
        opened.return_value.__exit__.assert_called_once()


def test_interruption_is_logged(root):
    with (
        patch("car.src.camera.camera.Camera", side_effect=KeyboardInterrupt),
        pytest.raises(KeyboardInterrupt),
    ):
        run_check(root, "camera", stream=io.StringIO())
    assert (
        "INTERRUPTED" in next(root.glob("system/hardware_tests/logs/*.log")).read_text()
    )


@pytest.mark.parametrize("directory", ["../logs", "/tmp/logs", "."])
def test_log_path_must_stay_inside_car(directory):
    with pytest.raises(ValueError):
        HardwareTestsConfig(
            log_directory=directory,
            camera_frames=1,
            arduino_samples=1,
            response_timeout_seconds=1.0,
        )


def test_hardware_menu_order_and_back(root):
    with patch(
        "car.system.management.hardware_tests.select_item", return_value=None
    ) as select:
        from car.system.management.hardware_tests import hardware_tests_menu

        hardware_tests_menu(root)
        select.assert_called_once_with(
            "Hardware tests",
            ["Camera check", "Arduino communication check", "Joystick check"],
        )


def test_hardware_menu_registered():
    from car.system.management.application import default_items

    assert "Hardware tests" in [item.label for item in default_items()]


def test_missing_optional_diagnostics_settings_returns_to_management(root):
    from car.src.config import load_config
    from car.system.management.application import MenuItem, run_management

    path = root / "config.toml"
    path.write_text(path.read_text().split("[hardware_tests]")[0])
    assert load_config(path).hardware_tests is None
    pages = []
    choices = iter([0, None])
    with patch("car.src.camera.camera.Camera") as camera:
        run_management(
            root,
            items=[MenuItem("Hardware tests", lambda root: run_check(root, "camera"))],
            select=lambda *args: next(choices),
            display=lambda *args: pages.append(args),
        )
        camera.assert_not_called()
    assert pages[0][0] == "Hardware tests unavailable"
    assert "Configure [hardware_tests]" in pages[0][1]


def test_joystick_requires_both_controls_and_logs_read_latency(root):
    from car.src.joystick import ControlInput
    from car.system.management.joystick_preview import preview_loop

    joystick = MagicMock()
    joystick.read.side_effect = [
        ControlInput(0.0, 0.0),
        ControlInput(0.0, 0.0),
        ControlInput(0.5, 0.0),
        ControlInput(0.5, 0.5),
    ]
    draws = []

    def preview(device, controls, settings, *, read):
        keys = iter(["\r", "\r", "\r"])
        return preview_loop(
            read,
            lambda timeout: next(keys),
            lambda *args: draws.append(args),
            refresh_seconds=settings.preview_refresh_seconds,
            idle_hint_seconds=settings.preview_idle_hint_seconds,
        )

    original = (root / "config.toml").read_bytes()
    with (
        patch("car.src.joystick.Joystick") as factory,
        patch(
            "car.system.management.joystick_preview.preview_controls",
            side_effect=preview,
        ),
        patch("car.src.communication.Communication.open") as communication,
    ):
        factory.return_value.__enter__.return_value = joystick
        transcript = run_check(root, "joystick", stream=io.StringIO())
        factory.return_value.__exit__.assert_called_once()
        communication.assert_not_called()
    assert "PASS" in transcript
    assert "Joystick initialization latency" in transcript
    assert "Axis metadata" in transcript
    assert "Joystick read latency ms: samples=4" in transcript
    assert "speed=0.500 steering=0.500" in transcript
    assert [frame[1:3] for frame in draws] == [
        (False, False),
        (True, False),
        (True, True),
    ]
    assert (root / "config.toml").read_bytes() == original


@pytest.mark.parametrize(
    "outcome", [False, OSError("controller disconnected"), KeyboardInterrupt()]
)
def test_joystick_cancel_failure_and_interrupt_release_device(root, outcome):
    from car.src.joystick import ControlInput

    joystick = MagicMock()
    joystick.read.return_value = ControlInput(0.0, 0.0)

    def preview(*args, read, **kwargs):
        read()
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    with (
        patch("car.src.joystick.Joystick") as factory,
        patch(
            "car.system.management.joystick_preview.preview_controls",
            side_effect=preview,
        ),
    ):
        factory.return_value.__enter__.return_value = joystick
        if isinstance(outcome, KeyboardInterrupt):
            with pytest.raises(KeyboardInterrupt):
                run_check(root, "joystick", stream=io.StringIO())
            transcript = next(
                root.glob("system/hardware_tests/logs/joystick-*.log")
            ).read_text()
            assert "INTERRUPTED" in transcript
        else:
            transcript = run_check(root, "joystick", stream=io.StringIO())
            assert (
                "FAIL" if isinstance(outcome, OSError) else "CANCELLED"
            ) in transcript
        assert "PASS" not in transcript
        assert "Joystick read latency ms: samples=1" in transcript
        factory.return_value.__exit__.assert_called_once()


def test_joystick_menu_dispatches_logged_check(root):
    from car.system.management import hardware_tests

    with (
        patch.object(hardware_tests, "select_item", side_effect=[2, None]),
        patch.object(hardware_tests, "open", return_value=io.StringIO(), create=True),
        patch.object(
            hardware_tests, "run_check", return_value="joystick report"
        ) as check,
        patch.object(hardware_tests, "show_page") as display,
    ):
        hardware_tests.hardware_tests_menu(root)
    assert check.call_args.args == (root, "joystick")
    display.assert_called_once_with("Joystick check", "joystick report")
