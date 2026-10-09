// Shared firmware identity protocol. No serial reader: the sketch owns
// dispatch.
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
} // namespace drivion
