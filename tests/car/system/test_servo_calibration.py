"""Guided calibration observations, lifecycle and firmware safety invariants."""

import shutil
import subprocess
from contextlib import contextmanager
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest

from car.src.communication import Acknowledgement
from car.src.communication import protocol as wire
from car.src.config import load_config
from car.system.arduino.management import calibration as setup
from tests.car.src.communication.test_arduino import compile_native

ROOT = Path(__file__).resolve().parents[3]
CAR = ROOT / "car"


@pytest.fixture
def parameters():
    return load_config().firmware["steering"]


@pytest.fixture
def settings(parameters):
    return setup.CalibrationSettings.load(CAR, parameters, load_config().communication)


def settle(wizard):
    while wizard.pulse != wizard.goal:
        previous = wizard.pulse
        wizard.pulse = wizard.next_pulse()
        assert abs(wizard.pulse - previous) <= wizard.settings.coarse_step_us


def press(wizard, key):
    wizard.key(key)
    settle(wizard)


def complete(wizard, inverted=False):
    # Discover a straight position different from the old 90-degree default.
    press(wizard, "D")
    press(wizard, "\r")
    press(wizard, "d")
    press(wizard, "l" if inverted else "r")
    press(wizard, "A")  # Logical left regardless of pulse direction.
    press(wizard, "\r")
    press(wizard, "D")
    press(wizard, "\r")
    for key in ("l", "r", "s", "\r"):
        press(wizard, key)


@pytest.mark.parametrize("inverted", [False, True])
def test_discover_straight_direction_and_endpoints(parameters, settings, inverted):
    wizard = setup.CalibrationWizard(parameters, settings)
    complete(wizard, inverted)
    values = wizard.values()
    assert wizard.done
    assert values["SERVO_CENTER_DEG"] == 94.5
    assert (values["SERVO_LEFT_DEG"] > values["SERVO_RIGHT_DEG"]) == inverted
    assert values["STEERING_LEFT_DEG"] == parameters["STEERING_LEFT_DEG"]


def test_no_direction_without_movement_and_no_save_without_verification(
    parameters, settings
):
    wizard = setup.CalibrationWizard(parameters, settings)
    press(wizard, "\r")
    press(wizard, "r")
    assert wizard.phase == "direction"
    press(wizard, "d")
    press(wizard, "r")
    press(wizard, "\r")
    assert wizard.phase == "left"  # Endpoint cannot be straight.
    with pytest.raises(ValueError):
        wizard.values()
    press(wizard, "A")
    press(wizard, "\r")
    press(wizard, "D")
    press(wizard, "\r")
    press(wizard, "\r")
    assert not wizard.done


@pytest.mark.parametrize(
    "key,disable",
    [("q", False), ("\x1b", False), ("x", True), ("n", True), ("c", True)],
)
def test_cancel_and_fault_choices(parameters, settings, key, disable):
    wizard = setup.CalibrationWizard(parameters, settings)
    wizard.key(key)
    assert wizard.cancelled
    assert wizard.disable == disable
    assert not wizard.done


def test_nudges_clamped_and_motion_does_not_accept_marks(parameters, settings):
    wizard = setup.CalibrationWizard(parameters, settings)
    for _ in range(100):
        press(wizard, "D")
    assert wizard.pulse == parameters["SERVO_MAX_US"]
    wizard.key("a")
    wizard.key("\r")
    assert wizard.center is None
    wizard.key("x")
    assert wizard.disable


class FakeClient:
    def __init__(self, *, drop=False, reject=False):
        self.sent = []
        self.pending = []
        self.sequence = 0
        self.drop, self.reject = drop, reject
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.closed = True

    def stop(self):
        pass

    def synchronize(self):
        self.sent.append("sync")

    def calibrate_steering(self, action, pulse, signature):
        self.sequence += 1
        self.sent.append((action, pulse, signature))
        if not self.drop:
            self.pending.append(
                Acknowledgement(
                    self.sequence,
                    wire.MessageType.CALIBRATE_STEERING,
                    wire.ErrorCode.BAD_PAYLOAD if self.reject else wire.ErrorCode.OK,
                )
            )
        return self.sequence

    def poll(self):
        pending, self.pending = self.pending, []
        return pending


def test_link_ack_rejection_loss_and_periodic_service(parameters, settings):
    from tests.car.src.communication.test_client import Clock

    clock = Clock()
    client = FakeClient()
    link = setup.CalibrationLink(client, parameters, settings, clock=clock)
    link.begin()
    assert [item[0] for item in client.sent] == [
        wire.CalibrationAction.BEGIN,
        wire.CalibrationAction.MOVE,
    ]
    clock.now = settings.sync_interval_seconds
    link.service()
    assert "sync" in client.sent
    link.finish()
    assert client.sent[-1][0] == wire.CalibrationAction.END
    client.reject = True
    with pytest.raises(RuntimeError, match="rejected"):
        link.move(1510)
    client.drop = True

    def ticking():
        clock.now += 0.1
        return clock.now

    link.clock = ticking
    with pytest.raises(TimeoutError, match="acknowledgement"):
        link.move(1510)


@pytest.fixture
def car_root(tmp_path):
    shutil.copytree(
        CAR / "system/arduino/sketches", tmp_path / "system/arduino/sketches"
    )
    shutil.copy(CAR / "config.toml", tmp_path / "config.toml")
    shutil.copy(CAR / "system/pyproject.toml", tmp_path / "system/pyproject.toml")
    return tmp_path


def run_wizard(root, keys, approvals, *, client=None, apply=None):
    events = iter(keys)
    approvals = iter(approvals)
    client = client or FakeClient()

    @contextmanager
    def terminal():
        class Keyboard:
            stream = StringIO()

            def key(self, _):
                value = next(events)
                if isinstance(value, BaseException):
                    raise value
                return value

        yield Keyboard()

    setup.guided_calibration(
        root,
        approve=lambda _: next(approvals),
        display=lambda *_: None,
        factory=lambda *_: client,
        terminal=terminal,
        apply=apply or (lambda _: None),
    )
    return client


def test_guided_save_and_apply(car_root):
    applied = []
    client = run_wizard(
        car_root,
        ["D", "\r", "d", "l", "A", "\r", "D", "\r", "l", "r", None, "s", "\r"],
        [True, True, True],
        apply=lambda root: applied.append(root),
    )
    values = load_config(car_root / "config.toml").firmware["steering"]
    assert values["SERVO_CENTER_DEG"] == 94.5
    assert values["SERVO_LEFT_DEG"] > values["SERVO_RIGHT_DEG"]
    assert applied == [car_root]
    assert client.closed
    assert client.sent[-1][0] == wire.CalibrationAction.END
    assert wire.CalibrationAction.MARK_CENTER in [item[0] for item in client.sent]


@pytest.mark.parametrize(
    "key,final_action",
    [
        ("q", wire.CalibrationAction.END),
        ("n", wire.CalibrationAction.DISABLE),
        ("c", wire.CalibrationAction.DISABLE),
        (KeyboardInterrupt(), wire.CalibrationAction.END),
    ],
)
def test_guided_cancel_restores_and_does_not_save(car_root, key, final_action):
    before = (car_root / "config.toml").read_bytes()
    client = FakeClient()
    if isinstance(key, KeyboardInterrupt):
        with pytest.raises(KeyboardInterrupt):
            run_wizard(car_root, [key], [True], client=client)
    else:
        run_wizard(car_root, [key], [True], client=client)
    assert client.closed
    assert client.sent[-1][0] == final_action
    assert (car_root / "config.toml").read_bytes() == before


def test_initial_refusal_and_rejected_firmware_do_not_save(car_root):
    before = (car_root / "config.toml").read_bytes()
    client = run_wizard(car_root, [], [False])
    assert not client.sent
    client = run_wizard(car_root, [], [True], client=FakeClient(reject=True))
    assert client.closed
    assert (car_root / "config.toml").read_bytes() == before


def test_firmware_calibration_limits_deadlines_and_fallback(tmp_path):
    (tmp_path / "Arduino.h").write_text(
        "#pragma once\n#include <stdint.h>\n#include <stddef.h>\n"
    )
    header = CAR / "system/arduino/library/DrivionServoCalibration.h"
    source = tmp_path / "calibration.cpp"
    source.write_text(
        f'#include "{header}"\n'
        + r"""
#include <assert.h>
using namespace drivion;
using namespace drivion::communication;
Result command(ServoCalibration &cal, uint8_t action, uint16_t pulse, uint32_t now, uint32_t deadline, bool badSignature=false) {
 uint8_t values[14]; put16(values,9); put16(values+2,1000); put16(values+4,2000);
 put16(values+6,1500); put16(values+8,25); put32(values+10,1000);
 uint8_t payload[9]; payload[0]=action; put16(payload+1,pulse); put32(payload+3,deadline);
 put16(payload+7,checksum(values,14)+(badSignature?1:0));
 return cal.command(payload,9,now);
}
int main() {
 ServoCalibration unknown(1000,2000,1500,25,1000,9);
 assert(command(unknown,0,1500,0,150,true)==BadPayload && !unknown.latched());
 assert(command(unknown,0,1500,0,150)==Ok && !unknown.outputEnabled());
 assert(command(unknown,1,1526,1,151)==BadPayload);
 assert(command(unknown,1,1525,1,151)==Ok && unknown.outputEnabled());
 assert(command(unknown,4,1500,2,152)==BadPayload);
 unknown.poll(151); assert(!unknown.outputEnabled());
 assert(command(unknown,1,1500,152,302)==Busy); // No rearming after a lost lease.
 ServoCalibration known(1000,2000,1500,25,1000,9);
 assert(command(known,0,1500,0,150)==Ok);
 assert(command(known,2,1500,1,151)==BadPayload); // Must first apply the pulse.
 assert(command(known,1,1525,1,151)==Ok);
 assert(command(known,2,1525,2,152)==Ok);
 assert(command(known,1,1550,3,153)==Ok);
 known.poll(153); assert(known.outputEnabled() && known.pulse()==1525);
 assert(command(known,0,1500,154,304)==Busy);
 assert(command(known,5,0,154,0)==Ok && !known.outputEnabled());
 ServoCalibration limits(1000,2000,1500,25,1000,9);
 assert(command(limits,0,1500,0,150)==Ok);
 assert(command(limits,1,999,1,151)==BadPayload);
 assert(command(limits,1,2001,1,151)==BadPayload);
 assert(command(limits,1,1510,150,150)==Expired);
 ServoCalibration wrap(1000,2000,1500,25,1000,9);
 assert(command(wrap,0,1500,UINT32_MAX-99,50)==Ok);
 assert(command(wrap,1,1510,UINT32_MAX-98,50)==Ok);
 wrap.poll(49); assert(wrap.outputEnabled());
 wrap.poll(50); assert(!wrap.outputEnabled());
}
"""
    )
    subprocess.run([str(compile_native(source))], check=True, timeout=10)


@pytest.mark.parametrize("save,apply_now", [(False, False), (True, False)])
def test_final_save_and_apply_can_be_declined(car_root, save, apply_now):
    before = (car_root / "config.toml").read_bytes()
    applied = []
    run_wizard(
        car_root,
        ["D", "\r", "d", "r", "A", "\r", "D", "\r", "l", "r", None, "s", "\r"],
        [True, save, apply_now],
        apply=lambda root: applied.append(root),
    )
    assert not applied
    assert ((car_root / "config.toml").read_bytes() != before) == save


def test_invalid_timing_or_step_rejected_before_hardware(car_root, parameters):
    path = car_root / "system/pyproject.toml"
    path.write_text(
        path.read_text().replace("coarse_step_us = 25", "coarse_step_us = 100")
    )
    with pytest.raises(ValueError, match="nudge limit"):
        setup.CalibrationSettings.load(
            car_root, parameters, load_config().communication
        )
    client = run_wizard(car_root, [], [])
    assert not client.sent


def test_guided_menu_dispatch(car_root):
    from car.system.arduino.management import menu

    choices = iter([4, None])
    with patch.object(menu, "guided_calibration") as action:
        menu.arduino_menu(car_root, select=lambda *_: next(choices))
    action.assert_called_once_with(car_root)
