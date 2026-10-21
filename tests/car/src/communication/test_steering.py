"""Exercise calibration math, firmware watchdog and management persistence."""

import subprocess
from pathlib import Path

import pytest

from car.src.communication.steering import steering_degrees
from car.src.config import load_config
from car.system.arduino.management.steering import configure_steering
from tests.car.src.communication.test_arduino import compile_native

ROOT = Path(__file__).resolve().parents[4]


def test_normalized_asymmetric_limits():
    params = {"STEERING_LEFT_DEG": 40, "STEERING_RIGHT_DEG": 25}
    for value, angle in [(-2, -40), (-0.5, -20), (0, 0), (0.5, 12.5), (2, 25)]:
        assert steering_degrees(value, params) == angle
    for value in (float("nan"), float("inf"), True):
        with pytest.raises(ValueError):
            steering_degrees(value, params)


def test_native_calibration_and_watchdog(tmp_path):
    header = ROOT / "car/system/arduino/library/DrivionSteering.h"
    source = tmp_path / "steering.cpp"
    source.write_text(
        f'#include "{header}"\n'
        "#include <assert.h>\n#include <limits>\n"
        "int main() {\n"
        "constexpr drivion::SteeringSettings settings{40,20,150,90,30,1000};\n"
        'static_assert(settings.valid(), "inverted calibration valid");\n'
        "drivion::Steering steering(settings);\n"
        "assert(steering.angle()==90);\n"
        "steering.setAngle(-2000, 5); assert(steering.angle()==120);\n"
        "steering.setAngle(1000, 10); assert(steering.angle()==60);\n"
        "steering.setAngle(3000, 20); assert(steering.angle()==30);\n"
        "assert(steering.pulseWidth(1000,2000)==1167);\n"
        "steering.poll(1019); assert(steering.angle()==30);\n"
        "steering.poll(1020); assert(steering.angle()==90);\n"
        "steering.setNormalized(-2, UINT32_MAX-499); assert(steering.angle()==150);\n"
        "steering.poll(499); assert(steering.angle()==150);\n"
        "steering.poll(500); assert(steering.angle()==90);\n"
        "steering.setNormalized(1, 600); steering.center(); assert(steering.angle()==90);\n"
        "steering.setNormalized(std::numeric_limits<float>::quiet_NaN(),700);\n"
        "assert(steering.angle()==90);\n"
        "constexpr drivion::SteeringSettings normal{40,20,20,80,140,1000};\n"
        "drivion::Steering direct(normal); direct.setNormalized(-0.5,0);\n"
        "assert(direct.angle()==50); direct.setNormalized(0.5,1); assert(direct.angle()==110);\n"
        "}\n"
    )
    subprocess.run([str(compile_native(source))], check=True, timeout=10)


@pytest.fixture
def steering_car(tmp_path):
    import shutil

    shutil.copytree(
        ROOT / "car/system/arduino/sketches", tmp_path / "system/arduino/sketches"
    )
    shutil.copy(ROOT / "car/config.toml", tmp_path / "config.toml")
    shutil.copy(ROOT / "car/system/pyproject.toml", tmp_path / "system/pyproject.toml")
    return tmp_path


def test_management_saves_inversion_and_timeout(steering_car):
    answers = iter([40.0, 20.0, 150.0, 90.0, 30.0, 10.0, 1200.0, None, None])
    configure_steering(
        steering_car,
        prompt=lambda _: next(answers),
        approve=lambda _: True,
        display=lambda *_: None,
    )
    values = load_config(steering_car / "config.toml").firmware["steering"]
    assert values["SERVO_LEFT_DEG"] == 150
    assert values["SERVO_PIN"] == 10
    assert values["STEERING_TIMEOUT_MS"] == values["COMMAND_TIMEOUT_MS"] == 1200


@pytest.mark.parametrize(
    "approve,answers",
    [
        (False, [None] * 9),
        (True, [40.0, 20.0, 90.0, 90.0, 90.0, 9.0, 1000.0, None, None]),
        (True, [None] * 5 + [9.5]),
    ],
)
def test_management_cancel_or_invalid_never_writes(steering_car, approve, answers):
    path = steering_car / "config.toml"
    before = path.read_bytes()
    entries = iter(answers)
    configure_steering(
        steering_car,
        prompt=lambda _: next(entries),
        approve=lambda _: approve,
        display=lambda *_: None,
    )
    assert path.read_bytes() == before


@pytest.fixture
def steering_firmware(tmp_path):
    """Execute the real sketch against wire frames with a fake servo output."""
    import shutil

    from car.system.arduino.firmware.compile import render_header, stage_library
    from car.system.arduino.firmware.definitions import load_firmware
    from car.system.arduino.settings import tool_settings

    car = ROOT / "car"
    shutil.copy(car / "system/arduino/sketches/steering/steering.ino", tmp_path)
    stage_library(tmp_path, car, tool_settings(car, "compile"))
    (tmp_path / "drivion_generated.h").write_text(
        render_header(
            "steering", load_firmware("steering", car), {}, tool_settings(car, "flash")
        )
    )
    (tmp_path / "Arduino.h").write_text(r"""
#pragma once
#include <stddef.h>
#include <stdint.h>
#include <deque>
#include <string>
#define F(value) value
struct Port {
 std::deque<uint8_t> rx;
 void begin(unsigned long) {}
 int available() {return int(rx.size());}
 int peek() {return rx.empty() ? -1 : rx.front();}
 int read() {int c=rx.front(); rx.pop_front(); return c;}
 int availableForWrite() {return 1;}
 size_t write(uint8_t) {return 1;}
 void println(const char*) {}
};
extern Port Serial;
constexpr int LOW = 0;
inline void digitalWrite(int, int) {}
uint32_t millis();
""")
    (tmp_path / "Servo.h").write_text(
        "struct Servo { int pulse=0; bool enabled=false; void writeMicroseconds(int p) {pulse=p;} void attach(int) {enabled=true;} bool attached(){return enabled;} void detach(){enabled=false;} };\n"
    )
    source = tmp_path / "runner.cpp"
    source.write_text(r"""
#include "Arduino.h"
#include <iostream>
#include <sstream>
Port Serial;
uint32_t now=0;
uint32_t millis() {return now;}
#include "steering.ino"
int main() {
 setup(); std::cout << (servo.attached() ? servo.pulse : -1) << "\n";
 std::string line;
 while(std::getline(std::cin,line)) {
  std::istringstream in(line); std::string hex; in >> now >> hex;
  if(hex!="-") for(size_t i=0;i<hex.size();i+=2) Serial.rx.push_back(uint8_t(std::stoul(hex.substr(i,2),nullptr,16)));
  for(int i=0;i<100;++i) loop();
  std::cout << (servo.attached() ? servo.pulse : -1) << "\n";
 }
}
""")

    return compile_native(source)


def test_sketch_centers_on_expiry_stop_session_and_bad_frames(steering_firmware):
    from car.src.communication import protocol as wire

    def packet(now, kind, sequence, payload=b"", session=1):
        return (
            f"{now} " + wire.encode(wire.Frame(kind, session, sequence, payload)).hex()
        )

    def target(deadline):
        return wire.TARGET.pack(0, 3000, deadline)

    messages = [
        packet(0, 1, 0),
        packet(1, 3, 1, target(1001)),
        packet(500, 3, 1, target(1500)),  # Replay cannot renew the deadline.
        "1000 -",
        "1001 -",
        packet(1002, 3, 2, target(2002)),
        packet(1003, 4, 3),
        packet(1004, 3, 4, target(2004)),
        packet(1005, 1, 0, session=2),
        packet(1006, 3, 1, target(2006), session=2),
        "2006 7e00ff7e",  # Corrupt traffic cannot prevent centering.
        packet(2007, 3, 2, target(2050), session=2),
        "2050 -",  # A shorter Pi lease is honored.
    ]
    result = subprocess.run(
        [str(steering_firmware)],
        input="\n".join(messages) + "\n",
        text=True,
        capture_output=True,
        check=True,
        timeout=10,
    )
    assert list(map(int, result.stdout.split())) == [
        1500,
        1500,
        1667,
        1667,
        1667,
        1500,
        1667,
        1500,
        1667,
        1500,
        1667,
        1500,
        1667,
        1500,
    ]


def test_sketch_calibration_replay_expiry_motion_lock_and_emergency(steering_firmware):
    from car.src.communication import protocol as wire
    from car.system.arduino.management.calibration import calibration_signature

    signature = calibration_signature(load_config().firmware["steering"])

    def packet(now, kind, sequence, payload=b"", session=1):
        return (
            f"{now} " + wire.encode(wire.Frame(kind, session, sequence, payload)).hex()
        )

    def command(now, sequence, action, pulse, deadline, session=1, token=signature):
        return packet(
            now,
            11,
            sequence,
            wire.CALIBRATION.pack(action, pulse, deadline, token),
            session,
        )

    messages = [
        packet(0, 1, 0),
        command(1, 1, 0, 1500, 151, token=signature ^ 1),  # Wrong running config.
        command(2, 2, 0, 1500, 152),
        command(3, 3, 1, 1510, 153),
        command(4, 4, 2, 1510, 154),
        command(5, 5, 1, 1535, 155),
        command(6, 6, 1, 1700, 156),  # Excessive movement rejected.
        command(100, 5, 1, 1535, 250),  # Replayed frame cannot extend the lease.
        "155 -",
        command(156, 7, 4, 1535, 306),  # Expired session cannot rearm.
        packet(157, 3, 8, wire.TARGET.pack(0, 3000, 307)),  # Drive remains locked.
        packet(158, 1, 0, session=2),
        command(159, 1, 5, 0, 0, session=2),  # Emergency disable needs no lease.
        packet(160, 1, 0, session=3),  # New handshake cannot undo disable.
        packet(161, 3, 1, wire.TARGET.pack(0, 3000, 311), session=3),
    ]
    result = subprocess.run(
        [str(steering_firmware)],
        input="\n".join(messages) + "\n",
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    assert list(map(int, result.stdout.split())) == [
        1500,
        1500,
        1500,
        -1,
        1510,
        1510,
        1535,
        1535,
        1535,
        1510,
        1510,
        1510,
        1510,
        -1,
        -1,
        -1,
    ]


def test_sketch_calibration_unknown_center_disables_on_disconnect(steering_firmware):
    from car.src.communication import protocol as wire
    from car.system.arduino.management.calibration import calibration_signature

    signature = calibration_signature(load_config().firmware["steering"])
    frames = [
        wire.Frame(1, 1, 0),
        wire.Frame(11, 1, 1, wire.CALIBRATION.pack(0, 1500, 150, signature)),
        wire.Frame(11, 1, 2, wire.CALIBRATION.pack(1, 1525, 152, signature)),
    ]
    messages = [
        f"{now} {wire.encode(frame).hex()}" for now, frame in zip((0, 1, 2), frames)
    ] + ["152 -"]
    result = subprocess.run(
        [str(steering_firmware)],
        input="\n".join(messages) + "\n",
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    assert list(map(int, result.stdout.split())) == [1500, 1500, -1, 1525, -1]
