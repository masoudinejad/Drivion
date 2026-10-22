"""Exercise shared text management parsing before binary communication starts."""

import subprocess
from pathlib import Path

from tests.car.src.communication.test_arduino import compile_native


def test_bounded_identity_reader_and_binary_handoff(tmp_path):
    header = (
        Path(__file__).resolve().parents[3]
        / "car/system/arduino/library/DrivionFirmware.h"
    )
    (tmp_path / "Arduino.h").write_text("#pragma once\n#include <stddef.h>\n")
    source = tmp_path / "commands.cpp"
    source.write_text(
        f'#include "{header}"\n'
        + r"""
#include <cassert>
#include <string>
struct Port {
  std::string input, output;
  int available() { return int(input.size()); }
  int peek() { return input.empty() ? -1 : static_cast<unsigned char>(input[0]); }
  int read() {
    int value = peek();
    if (value >= 0) input.erase(0, 1);
    return value;
  }
  void println(const char *value) { output += std::string(value) + "\n"; }
};
int main() {
  Port port;
  drivion::ManagementCommands<5> commands;
  const auto poll = [&](size_t budget, int flag = -1) {
    return commands.poll(port, "INFO", "identity", budget, flag);
  };
  port.input = "INFO\r\n";
  assert(!poll(0) && port.input == "INFO\r\n");
  assert(!poll(2) && port.input == "FO\r\n" && port.output.empty());
  assert(!poll(4) && port.input.empty() && port.output == "identity\n");
  port.output.clear();
  port.input = "overflowINFO\nNOPE\nINFO\n";
  while (port.available()) assert(!poll(2));
  assert(port.output == "identity\n"); // Discard the entire overlong line.
  port.output.clear();
  port.input = "IN";
  assert(!poll(2, 0x7e));
  port.input = "\x7e" "binary";
  assert(poll(32, 0x7e));
  assert(port.input == "\x7e" "binary" && port.output.empty());
}
"""
    )
    subprocess.run([str(compile_native(source))], check=True, timeout=10)
