"""Verify normalized controller demands, device lifetime, and guided calibration."""

from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from car.src.config import load_config, update_config
from car.src.configuration.schema import JoystickAxisConfig
from car.src.joystick import ControlInput, Joystick
from car.src.joystick.discovery import Controller
from car.src.joystick.joystick import interpret_axis
from car.system.management.joystick_setup import configure_controls


@pytest.fixture
def settings():
    config = load_config().joystick.with_overrides(
        name="Gamepad", vendor=1, product=2, unique_id="serial"
    )
    speed = JoystickAxisConfig(
        axis="ABS_Y", minimum=-100, centre=0, maximum=100, inverted=True
    )
    steering = JoystickAxisConfig(
        axis="ABS_RX", minimum=-100, centre=0, maximum=100, inverted=False
    )
    return config.with_overrides(
        controls=config.controls.with_overrides(
            speed=speed, steering=steering, dead_zone=0.1
        )
    )


def axis(value):
    return SimpleNamespace(value=value, min=-100, max=100)


class Device:
    name = "Gamepad"
    uniq = "serial"
    info = SimpleNamespace(vendor=1, product=2)

    def __init__(self):
        self.values = {1: 0, 3: 0}
        self.closed = False
        self.fail = False

    def capabilities(self, **kwargs):
        return {3: [(1, axis(0)), (3, axis(0))]}

    def absinfo(self, code):
        if self.fail:
            raise OSError("disconnected")
        return axis(self.values[code])

    def close(self):
        self.closed = True


@pytest.fixture
def runtime(settings, monkeypatch):
    from car.src.joystick import joystick as module

    feedback = []
    monkeypatch.setattr(
        module,
        "show_progress",
        lambda message: feedback.append(message) or nullcontext(),
    )
    monkeypatch.setattr(module, "show_success", feedback.append)
    device = Device()
    backend = SimpleNamespace(
        InputDevice=lambda *args, **kwargs: device,
        ecodes=SimpleNamespace(EV_ABS=3, ABS={1: "ABS_Y", 3: "ABS_RX"}),
    )
    observed = Controller(settings, "event9", "")
    return device, backend, lambda: ([observed], []), feedback


@pytest.mark.parametrize(
    "raw,expected",
    [
        (-200, -1),
        (-100, -1),
        (-55, -0.5),
        (-10, 0),
        (0, 0),
        (10, 0),
        (55, 0.5),
        (100, 1),
        (200, 1),
    ],
)
def test_proportional_values_and_dead_zone(settings, raw, expected):
    assert interpret_axis(
        raw, settings.controls.steering, 0.1, "accurate"
    ) == pytest.approx(expected)


@pytest.mark.parametrize("mode", ["accurate", "fixed"])
@pytest.mark.parametrize("allow_reverse", [False, True])
def test_runtime_speed_direction_reverse_and_independent_modes(
    settings, runtime, mode, allow_reverse
):
    device, backend, scan, feedback = runtime
    config = settings.with_overrides(
        controls=settings.controls.with_overrides(
            speed_mode=mode, steering_mode="accurate", allow_reverse=allow_reverse
        )
    )
    with Joystick(config, backend=backend, scan=scan) as joystick:
        assert feedback == ["Initializing joystick", "Joystick initialized: Gamepad"]
        for raw, direction in [(-55, 1), (55, -1), (0, 0)]:
            device.values = {1: raw, 3: 55}
            result = joystick.read()
            magnitude = 1 if mode == "fixed" else 0.5
            expected = direction * magnitude
            if not allow_reverse:
                expected = max(0, expected)
            assert result.speed == pytest.approx(expected)
            assert result.steering == pytest.approx(0.5)
            assert joystick.read() == result  # Idle sticks do not expire.
    assert device.closed
    with pytest.raises(RuntimeError):
        joystick.read()


@pytest.mark.parametrize("raw,expected", [(-55, -1), (0, 0), (5, 0), (55, 1)])
def test_fixed_steering(settings, runtime, raw, expected):
    device, backend, scan, _ = runtime
    config = settings.with_overrides(
        controls=settings.controls.with_overrides(steering_mode="fixed")
    )
    with Joystick(config, backend=backend, scan=scan) as joystick:
        device.values[3] = raw
        assert joystick.read().steering == expected


def test_disconnect_invalidates_client(settings, runtime):
    device, backend, scan, _ = runtime
    joystick = Joystick(settings, backend=backend, scan=scan)
    device.fail = True
    with pytest.raises(OSError, match="disconnected"):
        joystick.read()
    assert device.closed
    with pytest.raises(RuntimeError):
        joystick.read()


def test_failed_initialization_closes_without_success(settings, runtime):
    device, backend, scan, feedback = runtime
    device.uniq = "another-device"
    with pytest.raises(RuntimeError, match="changed"):
        Joystick(settings, backend=backend, scan=scan)
    assert device.closed
    assert feedback == ["Initializing joystick"]


def test_uncalibrated_input_requires_setup(settings, runtime):
    _, backend, scan, feedback = runtime
    config = settings.with_overrides(
        controls=settings.controls.with_overrides(speed=None, steering=None)
    )
    with pytest.raises(ValueError, match="Configure"):
        Joystick(config, backend=backend, scan=scan)
    assert feedback == ["Initializing joystick"]
    with (
        Joystick(config, backend=backend, scan=scan, for_setup=True) as joystick,
        pytest.raises(ValueError, match="calibrated"),
    ):
        joystick.read()


def test_asymmetric_calibration(settings):
    calibration = settings.controls.steering.with_overrides(
        minimum=-20, centre=10, maximum=110
    )
    assert interpret_axis(-5, calibration, 0, "accurate") == -0.5
    assert interpret_axis(60, calibration, 0, "accurate") == 0.5


@pytest.mark.parametrize(
    "overrides",
    [
        {"dead_zone": 1.0},
        {"dead_zone": -0.1},
        {"dead_zone": float("nan")},
        {"speed_mode": "unknown"},
    ],
)
def test_invalid_control_config(settings, overrides):
    with pytest.raises(ValidationError):
        settings.controls.with_overrides(**overrides)


def test_calibration_rejects_duplicate_axes_and_bad_bounds(settings):
    with pytest.raises(ValidationError):
        settings.controls.with_overrides(speed=settings.controls.steering)
    with pytest.raises(ValidationError):
        settings.controls.speed.with_overrides(centre=100)


def snapshot(speed=0, steering=0):
    return {"ABS_Y": axis(speed), "ABS_RX": axis(steering)}


@pytest.mark.parametrize("cancel_at", list(range(12)) + [None])
def test_guided_setup_saves_atomically_or_cancels(tmp_path, settings, cancel_at):
    path = tmp_path / "config.toml"
    path.write_text(Path("car/config.toml").read_text())
    update_config("joystick", settings.model_dump(exclude_none=True), path)
    metadata = tmp_path / "system/pyproject.toml"
    metadata.parent.mkdir()
    metadata.write_text(Path("car/system/pyproject.toml").read_text())
    original = path.read_bytes()
    samples = iter(
        [
            snapshot(),
            snapshot(0, -100),
            snapshot(0, 100),
            snapshot(),
            snapshot(100, 0),
            snapshot(-100, 0),
            snapshot(),
        ]
    )
    steps = []
    closed = []

    def answer(default):
        steps.append(len(steps))
        return None if len(steps) - 1 == cancel_at else default

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            closed.append(True)

        def axis_snapshot(self):
            return next(samples)

    configure_controls(
        tmp_path,
        factory=lambda *args, **kwargs: Session(),
        ask=lambda question: bool(answer(True)),
        save=lambda question: bool(answer(True)),
        preview=lambda *args: bool(answer(True)),
        select=lambda *args: answer(1),
        number=lambda *args: answer(0.05),
    )
    assert closed
    if cancel_at is not None:
        assert path.read_bytes() == original
    else:
        controls = load_config(path).joystick.controls
        assert controls.speed.axis == "ABS_Y" and controls.speed.inverted
        assert controls.steering.axis == "ABS_RX" and not controls.steering.inverted
        assert controls.speed_mode == controls.steering_mode == "fixed"
        assert not controls.allow_reverse
        assert "None" not in path.read_text()


def test_reselection_preserves_calibration_and_new_device_clears_it(tmp_path, settings):
    from car.system.management.joystick import select_joystick

    path = tmp_path / "config.toml"
    path.write_text(Path("car/config.toml").read_text())
    update_config("joystick", settings.model_dump(exclude_none=True), path)
    for identity in (settings, settings.with_overrides(unique_id="another")):
        device = Controller(identity, "event9", "")
        select_joystick(
            tmp_path, select=lambda *args: 0, scan=lambda device=device: ([device], [])
        )
        saved = load_config(path).joystick
        if identity.unique_id == settings.unique_id:
            assert saved.controls == settings.controls
        else:
            assert saved.controls.speed is None and saved.controls.steering is None
            assert saved.controls.dead_zone == settings.controls.dead_zone


def test_missing_axis_closes_device(settings, runtime):
    device, backend, scan, feedback = runtime
    backend.ecodes.ABS = {1: "ABS_Y", 3: "ABS_X"}
    with pytest.raises(ValueError, match="unavailable"):
        Joystick(settings, backend=backend, scan=scan)
    assert device.closed
    assert feedback == ["Initializing joystick"]


def test_changed_range_closes_device(settings, runtime):
    device, backend, scan, feedback = runtime
    config = settings.with_overrides(
        controls=settings.controls.with_overrides(
            speed=settings.controls.speed.with_overrides(minimum=-200)
        )
    )
    with pytest.raises(ValueError, match="range changed"):
        Joystick(config, backend=backend, scan=scan)
    assert device.closed
    assert feedback == ["Initializing joystick"]


def test_capture_retries_only_failed_endpoint_and_keeps_previous_samples():
    from car.system.management.joystick_setup import capture_axis

    samples = iter(
        [
            snapshot(0, 0),  # Invalid first endpoint: no movement.
            snapshot(0, -100),  # Valid first endpoint.
            snapshot(0, -70),  # Invalid opposite endpoint: still on the same side.
            snapshot(100, 100),  # Valid intended axis, unrelated motion is ignored.
        ]
    )
    prompts = []
    joystick = SimpleNamespace(axis_snapshot=lambda: next(samples))
    result = capture_axis(
        joystick,
        snapshot(),
        "LEFT",
        "RIGHT",
        0.25,
        1.5,
        lambda prompt: prompts.append(prompt) or True,
    )
    assert [prompt.endswith("LEFT") for prompt in prompts] == [True, True, False, False]
    assert "previous reading is kept" in prompts[-1]
    assert result.axis == "ABS_RX"
    assert (result.minimum, result.maximum) == (-100, 100)


def test_f710_forward_capture_ignores_previously_assigned_steering():
    from car.system.management.joystick_setup import capture_axis

    def f710_values(speed, steering=128):
        return {
            "ABS_Y": SimpleNamespace(value=speed, min=-32768, max=32767),
            "ABS_RX": SimpleNamespace(value=steering, min=-32768, max=32767),
            "ABS_Z": SimpleNamespace(value=0, min=0, max=255),
        }

    samples = iter(
        [
            f710_values(32767, 32767),
            f710_values(-129, 32767),  # Forward not yet held: retry this reading.
            f710_values(-32768, 32767),
        ]
    )
    prompts = []
    result = capture_axis(
        SimpleNamespace(axis_snapshot=lambda: next(samples)),
        f710_values(-129),
        "DOWN",
        "UP",
        0.25,
        1.5,
        lambda text: prompts.append(text) or True,
        excluded=("ABS_RX",),
    )
    assert len(prompts) == 3 and prompts[0] == "DOWN"
    assert result.axis == "ABS_Y" and result.inverted
    assert interpret_axis(-32768, result, 0.05, "accurate") == 1
    assert interpret_axis(32767, result, 0.05, "accurate") == -1


def test_capture_and_save_use_selection_instead_of_typed_boolean(monkeypatch):
    from car.system.management import joystick_setup

    calls = []
    monkeypatch.setattr(
        joystick_setup, "select_item", lambda title, labels: calls.append(labels) or 0
    )
    assert joystick_setup.capture_reading("Hold stick")
    assert joystick_setup.save_settings("Save?")
    assert calls == [["Capture reading"], ["Save settings"]]
    monkeypatch.setattr(joystick_setup, "select_item", lambda *args: None)
    assert not joystick_setup.capture_reading("Hold stick")


def test_preview_uses_pending_controls_without_mutating_settings(settings, runtime):
    device, backend, scan, _ = runtime
    pending = settings.controls.with_overrides(speed_mode="fixed", allow_reverse=False)
    with Joystick(settings, backend=backend, scan=scan) as joystick:
        device.values[1] = -55
        assert joystick.read(controls=pending).speed == 1
        assert joystick.read().speed == pytest.approx(0.5)
        device.values[1] = 55
        assert joystick.read(controls=pending).speed == 0
        assert joystick.config == settings


def test_check_controls_uses_saved_settings_without_modifying_config(
    tmp_path, settings, monkeypatch
):
    from contextlib import nullcontext

    from car.system.management import joystick as management
    from car.system.ui import terminal as terminal_module

    path = tmp_path / "config.toml"
    path.write_text(Path("car/config.toml").read_text())
    update_config("joystick", settings.model_dump(exclude_none=True), path)
    original = path.read_bytes()
    reader = SimpleNamespace(fileno=lambda: 42, read=lambda count: "\x1b")
    opened = []
    shown = []
    closed = []
    restored = []
    terminal = SimpleNamespace()
    monkeypatch.setattr(
        terminal_module,
        "open",
        lambda path, mode="r", **kwargs: nullcontext(
            reader if mode == "r" else terminal
        ),
        raising=False,
    )
    monkeypatch.setattr(
        terminal_module.select, "select", lambda *args: ([reader], [], [])
    )
    monkeypatch.setattr(terminal_module.termios, "tcgetattr", lambda fd: "old-terminal")
    monkeypatch.setattr(
        terminal_module.termios, "tcsetattr", lambda *args: restored.append(args)
    )
    monkeypatch.setattr(terminal_module.tty, "setcbreak", lambda fd: None)
    monkeypatch.setattr(terminal_module.os, "read", lambda *args: b"\x1b")
    monkeypatch.setenv("TERM", "xterm")

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            closed.append(True)

        def read(self):
            return ControlInput(0.5, -0.5)

    class Monitor:
        refresh_seconds = 0.1

        def __init__(self, **kwargs):
            shown.append(kwargs)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            pass

        def update(self, speed, steering, **kwargs):
            shown.append((speed, steering))

    management.check_controls(
        tmp_path,
        factory=lambda config: opened.append(config) or Session(),
        monitor_factory=Monitor,
    )
    assert opened == [settings]
    assert shown[0]["speed_mode"] == settings.controls.speed_mode
    assert shown[1] == (0.5, -0.5)
    assert closed and restored == [
        (42, terminal_module.termios.TCSADRAIN, "old-terminal")
    ]
    assert path.read_bytes() == original


@pytest.mark.parametrize("override", ["unavailable", "outside_range"])
def test_pending_mapping_validation_preserves_live_session(settings, runtime, override):
    device, backend, scan, _ = runtime
    speed = settings.controls.speed.with_overrides(
        **({"axis": "ABS_UNKNOWN"} if override == "unavailable" else {"minimum": -200})
    )
    pending = settings.controls.with_overrides(speed=speed)
    with Joystick(settings, backend=backend, scan=scan) as joystick:
        with pytest.raises(ValueError):
            joystick.read(controls=pending)
        assert not device.closed
        assert joystick.read() == ControlInput(0, 0)


def test_saved_mapping_detects_range_change_during_runtime(settings, runtime):
    device, backend, scan, _ = runtime
    with Joystick(settings, backend=backend, scan=scan) as joystick:
        device.absinfo = lambda code: SimpleNamespace(value=0, min=-50, max=50)
        with pytest.raises(ValueError, match="range changed"):
            joystick.read()


def test_invalid_dead_zone_retries_without_recapturing_sticks(tmp_path, settings):
    path = tmp_path / "config.toml"
    path.write_text(Path("car/config.toml").read_text())
    metadata = tmp_path / "system/pyproject.toml"
    metadata.parent.mkdir()
    metadata.write_text(Path("car/system/pyproject.toml").read_text())
    samples = iter(
        [
            snapshot(),
            snapshot(0, -100),
            snapshot(0, 100),
            snapshot(),
            snapshot(100, 0),
            snapshot(-100, 0),
            snapshot(),
        ]
    )
    values = iter([1.0, -0.1, float("nan"), 0.08])
    prompts, captures, previewed = [], [], []

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            pass

        def axis_snapshot(self):
            captures.append(True)
            return next(samples)

    def answer(question):
        prompts.append(question)
        return next(values)

    configure_controls(
        tmp_path,
        ask=lambda *args: True,
        select=lambda *args: 0,
        number=answer,
        factory=lambda *args, **kwargs: Session(),
        preview=lambda client, controls, metadata: previewed.append(controls) or True,
        save=lambda *args: True,
    )
    assert len(captures) == 7  # No samples were requested again after invalid settings.
    assert len(prompts) == 4 and "Calibration is kept" in prompts[-1]
    saved = load_config(path).joystick.controls
    assert saved.dead_zone == 0.08
    assert saved == previewed[0]
    assert saved.speed.axis == "ABS_Y" and saved.steering.axis == "ABS_RX"
