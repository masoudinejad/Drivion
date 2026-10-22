// Shared firmware identity dispatch and optional bounded management reader.
#pragma once

#include <Arduino.h>
#include <string.h>

namespace drivion {
// Accept any Arduino-compatible serial stream and RAM/flash response string.
// Unknown commands remain available to the sketch's other command handlers.
template <typename SerialPort, typename Response>
bool handleInfo(SerialPort &serial, const char *command,
                const char *infoCommand, Response response) {
  if (command == nullptr || strcmp(command, infoCommand) != 0) {
    return false;
  }
  serial.println(response);
  return true;
}

// For sketches whose only text command is INFO. Reject complete overlong lines
// and optionally hand off to the binary parser without consuming its delimiter.
// The sketch chooses the per-loop byte budget and owns the parser lifetime.
template <size_t Capacity> class ManagementCommands {
  static_assert(Capacity > 1,
                "Command buffer must include a token and its NUL");

public:
  template <typename SerialPort, typename Response>
  bool poll(SerialPort &serial, const char *infoCommand, Response response,
            size_t budget, int binaryFlag = -1) {
    while (budget-- && serial.available() > 0) {
      if (binaryFlag >= 0 && serial.peek() == binaryFlag)
        return true;
      const int incoming = serial.read();
      if (incoming < 0)
        break;
      if (incoming == '\n') {
        if (!discard_) {
          command_[length_] = '\0';
          handleInfo(serial, command_, infoCommand, response);
        }
        length_ = 0;
        discard_ = false;
      } else if (incoming != '\r' && !discard_) {
        if (length_ + 1 < Capacity)
          command_[length_++] = char(incoming);
        else
          discard_ = true;
      }
    }
    return false;
  }

private:
  char command_[Capacity]{};
  size_t length_ = 0;
  bool discard_ = false;
};
} // namespace drivion
