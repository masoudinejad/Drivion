// Communication-only demonstration: reported values echo targets, not sensors.
#include "drivion_generated.h"
#include "src/DrivionFirmware/DrivionCommunication.h"
#include "src/DrivionFirmware/DrivionFirmware.h"

namespace {
using namespace drivion::communication;
static_assert(DRIVION_PROTOCOL_VERSION == Version,
              "Firmware metadata must match the communication wire version");
constexpr Settings settings{COMMAND_TIMEOUT_MS, FRAME_TIMEOUT_MS,
                            STATUS_INTERVAL_MS, MAX_TELEMETRY_INTERVAL_MS,
                            RX_BUDGET_BYTES,    TX_BUDGET_BYTES};
static_assert(settings.valid(), "Invalid generated communication parameters");
ReportedValues reported{};
void onEvent(void *, Event event, const Target &target) {
  // Real firmware chooses its own control and stop policy in this callback.
  if (event == Event::Target) {
    reported = ReportedValues{millis(), target.speedMmS,
                              target.steeringCentidegrees, AllFields};
  } else {
    reported.validFields = 0;
  }
}
Communication<decltype(Serial)> communication(Serial, settings, onEvent,
                                              nullptr);
// Preserve existing INFO management queries before entering a binary session.
char command[sizeof(DRIVION_INFO_COMMAND)]{};
size_t commandLength = 0;
bool discardCommand = false;
bool binaryMode = false;
void pollManagement() {
  for (uint16_t budget = RX_BUDGET_BYTES; budget && Serial.available();
       --budget) {
    // The delimiter switches parsers without consuming the binary frame start.
    if (Serial.peek() == Flag) {
      binaryMode = true;
      return;
    }
    const int incoming = Serial.read();
    if (incoming < 0)
      return;
    if (incoming == '\n') {
      if (!discardCommand) {
        command[commandLength] = '\0';
        drivion::handleInfo(Serial, command, DRIVION_INFO_COMMAND,
                            F(DRIVION_INFO_RESPONSE));
      }
      commandLength = 0;
      discardCommand = false;
    } else if (incoming != '\r' && !discardCommand) {
      if (commandLength + 1 < sizeof(command))
        command[commandLength++] = char(incoming);
      else
        discardCommand = true;
    }
  }
}
} // namespace

void setup() {
  Serial.begin(DRIVION_SERIAL_BAUD_RATE);
  communication.begin();
}
void loop() {
  if (!binaryMode)
    pollManagement();
  if (binaryMode) {
    communication.publish(reported);
    communication.poll(millis());
  }
}
