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
            "Hardware tests", ["Camera check", "Arduino communication check"]
        )


def test_hardware_menu_registered():
    from car.system.management.application import default_items

    assert "Hardware tests" in [item.label for item in default_items()]
