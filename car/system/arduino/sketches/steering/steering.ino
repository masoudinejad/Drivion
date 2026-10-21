// Calibrated steering servo. Speed targets are not actuated or reported.
#include "drivion_generated.h"
#include "src/DrivionFirmware/DrivionCommunication.h"
#include "src/DrivionFirmware/DrivionFirmware.h"
#include "src/DrivionFirmware/DrivionServoCalibration.h"
#include "src/DrivionFirmware/DrivionSteering.h"
#include <Servo.h>

namespace {
using namespace drivion::communication;
static_assert(DRIVION_PROTOCOL_VERSION == Version,
              "Firmware metadata must match the communication wire version");
constexpr Settings settings{COMMAND_TIMEOUT_MS, FRAME_TIMEOUT_MS,
                            STATUS_INTERVAL_MS, MAX_TELEMETRY_INTERVAL_MS,
                            RX_BUDGET_BYTES,    TX_BUDGET_BYTES};
static_assert(settings.valid(), "Invalid generated communication parameters");
constexpr drivion::SteeringSettings calibration{
    STEERING_LEFT_DEG, STEERING_RIGHT_DEG, SERVO_LEFT_DEG,
    SERVO_CENTER_DEG,  SERVO_RIGHT_DEG,    STEERING_TIMEOUT_MS};
static_assert(calibration.valid(), "Invalid steering calibration");
static_assert(SERVO_PIN >= 2 && SERVO_PIN <= 19,
              "Use Nano D2-D19; D0/D1 are serial");
static_assert(SERVO_MIN_US >= 544 && SERVO_MIN_US < SERVO_MAX_US &&
                  SERVO_MAX_US <= 2400,
              "Invalid servo pulse limits");
Servo servo;
drivion::Steering steering(calibration);
static_assert(CALIBRATION_STEP_US >= 1 && CALIBRATION_STEP_US <= 100,
              "Invalid calibration nudge limit");
drivion::ServoCalibration calibrationSession(
    SERVO_MIN_US, SERVO_MAX_US,
    int(SERVO_MIN_US +
        SERVO_CENTER_DEG * (SERVO_MAX_US - SERVO_MIN_US) / 180.0f + 0.5f),
    CALIBRATION_STEP_US, STEERING_TIMEOUT_MS, SERVO_PIN);
void onEvent(void *, Event event, const Target &target);
Result onCalibration(void *, const uint8_t *, uint16_t, uint32_t);
Communication<decltype(Serial)> communication(Serial, settings, onEvent,
                                              nullptr, onCalibration);
Result onCalibration(void *, const uint8_t *payload, uint16_t size,
                     uint32_t now) {
  if (communication.commandActive())
    return Busy;
  const Result result = calibrationSession.command(payload, size, now);
  if (calibrationSession.latched())
    communication.disableMotion();
  return result;
}
void onEvent(void *, Event event, const Target &target) {
  if (calibrationSession.latched()) {
    calibrationSession.stop();
    return;
  }
  if (event == Event::Target)
    steering.setAngle(target.steeringCentidegrees, millis());
  else
    steering.center();
  // No steering sensor: do not claim that the demanded angle was measured.
}
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
  // Preload straight before attach, avoiding Servo's default center pulse.
  servo.writeMicroseconds(steering.pulseWidth(SERVO_MIN_US, SERVO_MAX_US));
  servo.attach(SERVO_PIN);
  Serial.begin(DRIVION_SERIAL_BAUD_RATE);
  communication.begin();
}
void loop() {
  if (!binaryMode)
    pollManagement();
  if (binaryMode)
    communication.poll(millis());
  if (calibrationSession.latched()) {
    calibrationSession.poll(millis());
    if (calibrationSession.outputEnabled()) {
      servo.writeMicroseconds(calibrationSession.pulse());
      if (!servo.attached())
        servo.attach(SERVO_PIN);
    } else if (servo.attached()) {
      servo.detach();
      digitalWrite(SERVO_PIN, LOW);
    }
  } else {
    steering.poll(millis());
    servo.writeMicroseconds(steering.pulseWidth(SERVO_MIN_US, SERVO_MAX_US));
  }
}
