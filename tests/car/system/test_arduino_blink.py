"""Verify the registered blink sketch and INFO protocol without flashing a board."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from car.system.arduino.firmware.compile import render_header, stage_library
from car.system.arduino.firmware.definitions import load_firmware
from car.system.arduino.settings import tool_settings

ROOT = Path(__file__).resolve().parents[3] / "car"
NAME = "board_setup_test"


def configuration():
    return {
        "firmware": {NAME: load_firmware(NAME, ROOT)},
        "firmware_compile": tool_settings(ROOT, "compile"),
        "firmware_flash": tool_settings(ROOT, "flash"),
    }


def stage_sketch(directory, config):
    sketch = directory / NAME
    sketch.mkdir()
    shutil.copy(ROOT / f"system/arduino/sketches/{NAME}/{NAME}.ino", sketch)
    header = render_header(NAME, config["firmware"][NAME], {}, config["firmware_flash"])
    (sketch / config["firmware_compile"]["header_filename"]).write_text(header)
    stage_library(sketch, ROOT, config["firmware_compile"])
    return sketch


def test_only_blink_parameter_is_required():
    firmware = configuration()["firmware"][NAME]
    assert set(firmware["parameters"]) == {"BLINK_DURATION_MS"}
    assert type(firmware["parameters"]["BLINK_DURATION_MS"]) is int
    assert firmware["parameters"]["BLINK_DURATION_MS"] > 0


def test_blink_timing_rollover_and_serial_identity(tmp_path):
    """Run the actual sketch against a minimal host-side Arduino API stub."""
    compiler = shutil.which("clang++") or shutil.which("g++")
    if compiler is None:
        pytest.skip("A host C++ compiler is required for the sketch behavior test")
    config = configuration()
    sketch = stage_sketch(tmp_path, config)
    (sketch / "Arduino.h").write_text(r"""
#pragma once
#include <cstddef>
#include <string>
constexpr int LED_BUILTIN = 13;
constexpr int OUTPUT = 1;
constexpr int HIGH = 1;
constexpr int LOW = 0;
#define F(value) value
struct SerialStub {
  std::string input;
  std::string output;
  unsigned long baud = 0;
  void begin(unsigned long value) { baud = value; }
  int available() { return input.size(); }
  int read() {
    if (input.empty()) return -1;
    const unsigned char value = input.front();
    input.erase(0, 1);
    return value;
  }
  void println(const char *value) { output += std::string(value) + "\n"; }
};
extern SerialStub Serial;
unsigned long millis();
void pinMode(int pin, int mode);
void digitalWrite(int pin, int state);
""")
    harness = sketch / "test.cpp"
    harness.write_text(r"""
#include "Arduino.h"
#include <cassert>
#include <iostream>
#include <limits>
SerialStub Serial;
unsigned long clockTime = 0;
int ledState = -1;
unsigned long millis() { return clockTime; }
void pinMode(int pin, int mode) { assert(pin == LED_BUILTIN && mode == OUTPUT); }
void digitalWrite(int pin, int state) { assert(pin == LED_BUILTIN); ledState = state; }
#include "board_setup_test.ino"
int main() {
  setup();
  assert(ledState == LOW && Serial.baud == DRIVION_SERIAL_BAUD_RATE);
  clockTime = blinkDuration - 1;
  loop();
  assert(ledState == LOW);
  clockTime = blinkDuration;
  loop();
  assert(ledState == HIGH);
  clockTime = 2 * blinkDuration - 1;
  loop();
  assert(ledState == HIGH);
  clockTime = 2 * blinkDuration;
  loop();
  assert(ledState == LOW);
  const unsigned long start = std::numeric_limits<unsigned long>::max() - (blinkDuration - 1);
  clockTime = start;
  setup();
  clockTime = start + blinkDuration - 1;
  loop();
  assert(ledState == LOW);
  clockTime = start + blinkDuration;
  loop();
  assert(ledState == HIGH);
  const std::string token = DRIVION_INFO_COMMAND;
  assert(!drivion::handleInfo(Serial, nullptr, DRIVION_INFO_COMMAND, F(DRIVION_INFO_RESPONSE)));
  assert(!drivion::handleInfo(Serial, "MOTOR", DRIVION_INFO_COMMAND, F(DRIVION_INFO_RESPONSE)));
  assert(Serial.output.empty());
  Serial.input = token.substr(0, 1);
  loop();
  assert(Serial.output.empty());
  Serial.input += token.substr(1) + "\r\n";
  while (Serial.available()) loop();
  std::cout << Serial.output;
  Serial.output.clear();
  Serial.input = "overflow" + token + "\n";
  while (Serial.available()) loop();
  assert(Serial.output.empty());
  Serial.input = token + "\n";
  while (Serial.available()) loop();
  std::cout << Serial.output;
}
""")
    executable = tmp_path / "blink-test"
    subprocess.run(
        [
            compiler,
            "-std=c++11",
            "-I",
            str(sketch),
            str(harness),
            "-o",
            str(executable),
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    result = subprocess.run(
        [str(executable)], capture_output=True, text=True, check=True, timeout=10
    )
    replies = [json.loads(line) for line in result.stdout.splitlines()]
    assert len(replies) == 2
    for reply in replies:
        assert reply["firmware_name"] == NAME
        assert reply["firmware_version"] == config["firmware"][NAME]["version"]
        assert reply["protocol_version"] == config["firmware"][NAME]["protocol_version"]


def test_registered_sketch_compiles_for_avr_when_toolchain_available(tmp_path):
    executable = shutil.which("arduino-cli")
    if executable is None:
        pytest.skip("Arduino CLI is not installed on this development machine")
    listing = subprocess.run(
        [executable, "core", "list", "--json"],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    platforms = json.loads(listing.stdout).get("platforms", [])
    if not any(
        item.get("id") == "arduino:avr" and item.get("installed_version")
        for item in platforms
    ):
        pytest.skip("Arduino AVR core is not installed on this development machine")
    config = configuration()
    sketch = stage_sketch(tmp_path, config)
    subprocess.run(
        [
            executable,
            "compile",
            "--fqbn",
            config["firmware"][NAME]["fqbn"],
            "--build-path",
            str(tmp_path / "build"),
            "--output-dir",
            str(tmp_path / "artifacts"),
            str(sketch),
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=config["firmware_compile"]["command_timeout_seconds"],
    )
    assert (tmp_path / f"artifacts/{NAME}.ino.hex").is_file()
