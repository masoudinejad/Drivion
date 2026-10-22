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
void onEvent(void *, Event event, const Target &target);
Communication<decltype(Serial)> communication(Serial, settings, onEvent,
                                              nullptr);
void onEvent(void *, Event event, const Target &target) {
  // Publish within the callback so replies in this poll see the updated state.
  // Real firmware chooses its own control and stop policy here.
  ReportedValues reported{};
  if (event == Event::Target) {
    reported = ReportedValues{millis(), target.speedMmS,
                              target.steeringCentidegrees, AllFields};
  }
  communication.publish(reported);
}
// Preserve INFO queries until the first binary frame starts.
drivion::ManagementCommands<sizeof(DRIVION_INFO_COMMAND)> management;
bool binaryMode = false;
} // namespace

void setup() {
  Serial.begin(DRIVION_SERIAL_BAUD_RATE);
  communication.begin();
}
void loop() {
  if (!binaryMode)
    binaryMode =
        management.poll(Serial, DRIVION_INFO_COMMAND, F(DRIVION_INFO_RESPONSE),
                        RX_BUDGET_BYTES, Flag);
  if (binaryMode)
    communication.poll(millis());
}
