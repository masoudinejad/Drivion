"""Execute the actual Arduino library against Python-produced wire messages."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from car.src.communication import protocol as wire
from car.src.config import load_config
from car.system.arduino.firmware.compile import render_header, stage_library
from car.system.arduino.firmware.definitions import load_firmware
from car.system.arduino.settings import tool_settings

ROOT = Path(__file__).resolve().parents[4]
CAR = ROOT / "car"


@pytest.fixture(scope="module")
def firmware(tmp_path_factory):
    compiler = shutil.which("clang++") or shutil.which("g++")
    if not compiler:
        pytest.skip("native C++ compiler unavailable")
    folder = tmp_path_factory.mktemp("communication-native")
    (folder / "Arduino.h").write_text(
        "#pragma once\n#include <stddef.h>\n#include <stdint.h>\n"
    )
    params = load_config().firmware["communication_demo"]
    header = CAR / "system/arduino/library/DrivionCommunication.h"
    source = folder / "runner.cpp"
    source.write_text(
        "#include <deque>\n#include <iostream>\n#include <sstream>\n#include <string>\n#include <iomanip>\n"
        f'#include "{header}"\n'
        "using namespace drivion::communication;\n"
        "struct Port { std::deque<unsigned char> rx; std::string tx; bool blocked=false;\n"
        " int available() { return int(rx.size()); }\n"
        " int read() { int c=rx.front(); rx.pop_front(); return c; }\n"
        " int availableForWrite() { return blocked ? 0 : 1; }\n"
        " size_t write(uint8_t c) {tx.push_back(char(c)); return 1;} };\n"
        "void event(void*, Event e, const Target& t) {\n"
        'std::cout << "E " << int(e) << " " << t.speedMmS << " " << t.steeringCentidegrees << " " << t.sequence << "\\n";}\n'
        "int main() { Port port; Settings settings{"
        + ",".join(
            str(params[key])
            for key in (
                "COMMAND_TIMEOUT_MS",
                "FRAME_TIMEOUT_MS",
                "STATUS_INTERVAL_MS",
                "MAX_TELEMETRY_INTERVAL_MS",
                "RX_BUDGET_BYTES",
                "TX_BUDGET_BYTES",
            )
        )
        + "}; Communication<Port> comm(port, settings, event, nullptr); if(!comm.begin()) return 2;\n"
        "std::string line; while(std::getline(std::cin,line)) {\n"
        "std::istringstream in(line); uint32_t now; std::string hex; in >> now >> hex;\n"
        'if(hex=="P") {int32_t speed; int angle, mask; in >> speed >> angle >> mask; comm.publish(ReportedValues{now,speed,int16_t(angle),uint16_t(mask)});}\n'
        'else if(hex=="B") port.blocked=true; else if(hex=="U") port.blocked=false;\n'
        'else if(hex!="-") {for(size_t i=0;i<hex.size();i+=2) port.rx.push_back(uint8_t(std::stoul(hex.substr(i,2),nullptr,16)));}\n'
        "for(int i=0;i<100;++i) comm.poll(now);\n"
        "std::cout << \"W \"; for(unsigned char c:port.tx) std::cout << std::hex << std::setfill('0') << std::setw(2) << unsigned(c);\n"
        'std::cout << std::dec << "\\n"; port.tx.clear(); } }\n'
    )
    executable = folder / "runner"
    subprocess.run(
        [
            compiler,
            "-std=c++11",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-I",
            str(folder),
            str(source),
            "-o",
            str(executable),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return executable


def run(firmware, lines):
    output = subprocess.run(
        [str(firmware)],
        input="\n".join(lines) + "\n",
        text=True,
        capture_output=True,
        check=True,
        timeout=10,
    ).stdout
    events = []
    frames = []
    decoder = wire.Decoder(1)
    for line in output.splitlines():
        if line.startswith("E "):
            events.append(tuple(map(int, line.split()[1:])))
        elif line.startswith("W "):
            frames += decoder.feed(bytes.fromhex(line[2:]), 0)
    return events, frames


def packet(now, kind, sequence, payload=b"", session=123):
    return f"{now} " + wire.encode(wire.Frame(kind, session, sequence, payload)).hex()


def test_cross_language_handshake_target_and_snapshot(firmware):
    events, frames = run(
        firmware,
        [
            packet(1000, wire.MessageType.HELLO, 0),
            packet(
                1020,
                wire.MessageType.DRIVE_TARGET,
                1,
                wire.TARGET.pack(-250, 1234, 1150),
            ),
            "1021 P -245 -1200 3",
            packet(1022, wire.MessageType.GET_TELEMETRY, 2),
        ],
    )
    assert events[:2] == [(3, 0, 0, 0), (0, -250, 1234, 1)]
    assert wire.WELCOME.unpack(frames[0].payload) == (1000, 200, 60000, 3)
    snapshot = next(f for f in frames if f.kind == wire.MessageType.SNAPSHOT)
    assert snapshot.sequence == 2
    assert wire.TELEMETRY.unpack(snapshot.payload) == (1021, -245, -1200, 3)


def test_deadline_replay_stop_and_wrong_session(firmware):
    events, frames = run(
        firmware,
        [
            packet(0, 1, 0),
            packet(1, 3, 1, wire.TARGET.pack(100, -100, 50)),
            packet(2, 3, 1, wire.TARGET.pack(200, 100, 100)),
            packet(3, 3, 2, wire.TARGET.pack(999, 100, 100), session=999),
            "50 -",
            "60 -",
            packet(61, 4, 3),
        ],
    )
    assert [e[0] for e in events] == [3, 0, 2, 1]
    assert [wire.ACK.unpack(f.payload) for f in frames if f.kind == 9] == [
        (3, 3),
        (4, 0),
    ]


def test_expired_target_and_timer_sequence_wrap(firmware):
    events, frames = run(
        firmware,
        [
            packet(0xFFFFFFF0, 1, 65534),
            packet(0xFFFFFFF1, 3, 65535, wire.TARGET.pack(100, 0, 20)),
            packet(0xFFFFFFF2, 3, 0, wire.TARGET.pack(200, 0, 21)),
            "21 -",
            packet(22, 3, 1, wire.TARGET.pack(300, 0, 20)),
        ],
    )
    assert [e[0] for e in events] == [3, 0, 0, 2]
    assert any(wire.ACK.unpack(f.payload) == (3, 4) for f in frames if f.kind == 9)


def test_stream_selection_off_and_snapshot_independence(firmware):
    _, frames = run(
        firmware,
        [
            packet(0, 1, 0),
            "1 P 100 -200 3",
            packet(2, 5, 1, wire.TELEMETRY_CONFIG.pack(10, 1)),
            "12 -",
            packet(13, 5, 2, wire.TELEMETRY_CONFIG.pack(0, 0)),
            "30 -",
            packet(31, 6, 3),
        ],
    )
    stream = [f for f in frames if f.kind == wire.MessageType.TELEMETRY]
    assert len(stream) == 1
    assert wire.TELEMETRY.unpack(stream[0].payload)[-1] == 1
    snapshot = next(f for f in frames if f.kind == wire.MessageType.SNAPSHOT)
    assert wire.TELEMETRY.unpack(snapshot.payload)[-1] == 3


def test_corruption_timeout_and_blocked_tx_do_not_starve_watchdog(firmware):
    bad = bytearray(wire.encode(wire.Frame(3, 123, 1, wire.TARGET.pack(200, 100, 120))))
    bad[3] ^= 1
    partial = wire.encode(wire.Frame(3, 123, 3, wire.TARGET.pack(300, 100, 400)))
    events, _ = run(
        firmware,
        [
            packet(0, 1, 0),
            "1 " + bytes(bad).hex(),
            packet(2, 3, 2, wire.TARGET.pack(100, 0, 100)),
            "3 B",
            "50 " + partial[:10].hex(),
            "151 " + partial[10:].hex(),
            "152 U",
        ],
    )
    assert [e[0] for e in events] == [3, 0, 2]


def test_demo_compiles_for_nano(tmp_path):
    cli = shutil.which("arduino-cli")
    if not cli:
        pytest.skip("Arduino CLI unavailable")
    cores = subprocess.run(
        [cli, "core", "list", "--json"],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    if not any(
        p.get("id") == "arduino:avr" and p.get("installed_version")
        for p in json.loads(cores.stdout).get("platforms", [])
    ):
        pytest.skip("Arduino AVR core unavailable")
    sketch = tmp_path / "communication_demo"
    shutil.copytree(CAR / "system/arduino/sketches/communication_demo", sketch)
    stage_library(sketch, CAR, tool_settings(CAR, "compile"))
    firmware = load_firmware("communication_demo", CAR)
    (sketch / "drivion_generated.h").write_text(
        render_header("communication_demo", firmware, {}, tool_settings(CAR, "flash"))
    )
    result = subprocess.run(
        [
            cli,
            "compile",
            "--fqbn",
            firmware["fqbn"],
            "--build-path",
            str(tmp_path / "build"),
            str(sketch),
        ],
        capture_output=True,
        text=True,
        timeout=tool_settings(CAR, "compile")["command_timeout_seconds"],
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_clock_refresh_preserves_targets_and_rejects_duplicate_hello(firmware):
    events, frames = run(
        firmware,
        [
            packet(0, 1, 0),
            packet(1, 3, 1, wire.TARGET.pack(100, 200, 150)),
            packet(2, 1, 2),
            packet(3, 1, 2),
            "100 -",
        ],
    )
    assert [event[0] for event in events] == [3, 0]
    welcomes = [frame for frame in frames if frame.kind == wire.MessageType.WELCOME]
    assert len(welcomes) == 2
    status = next(frame for frame in frames if frame.kind == wire.MessageType.STATUS)
    assert wire.STATUS.unpack(status.payload)[1:3] == (1, 1)


def test_oversized_frames_and_unknown_messages_recover(firmware):
    oversized = (b"\x7e" + b"x" * 200 + b"\x7e").hex()
    _, frames = run(
        firmware,
        [
            packet(0, 1, 0),
            "1 " + oversized,
            packet(2, 99, 1),
            packet(3, 5, 2, wire.TELEMETRY_CONFIG.pack(10, 4)),
            packet(4, 6, 3),
        ],
    )
    assert [
        wire.ACK.unpack(f.payload) for f in frames if f.kind == wire.MessageType.ACK
    ] == [(99, 2), (5, 1)]
    assert any(frame.kind == wire.MessageType.SNAPSHOT for frame in frames)
