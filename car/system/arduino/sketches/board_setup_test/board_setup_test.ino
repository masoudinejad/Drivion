// Board setup smoke test: blink the built-in LED and answer firmware INFO
// queries. Values and identity are generated from the TOML configuration.
#include "drivion_generated.h"
#include "src/DrivionFirmware/DrivionFirmware.h"

namespace {
constexpr unsigned long blinkDuration = BLINK_DURATION_MS;
static_assert(BLINK_DURATION_MS > 0 && BLINK_DURATION_MS == blinkDuration,
              "BLINK_DURATION_MS must be positive integer milliseconds");

unsigned long lastToggle = 0;
bool ledOn = false;
// The only supported command is the configured identity token, plus its NUL.
drivion::ManagementCommands<sizeof(DRIVION_INFO_COMMAND)> management;
} // namespace

void setup() {
  pinMode(LED_BUILTIN, OUTPUT);
  digitalWrite(LED_BUILTIN, LOW);
  lastToggle = millis();
  Serial.begin(DRIVION_SERIAL_BAUD_RATE);
}

void loop() {
  const unsigned long now = millis();
  // Unsigned subtraction remains correct when millis() rolls over.
  if (now - lastToggle >= blinkDuration) {
    lastToggle = now;
    ledOn = !ledOn;
    digitalWrite(LED_BUILTIN, ledOn ? HIGH : LOW);
  }
  management.poll(Serial, DRIVION_INFO_COMMAND, F(DRIVION_INFO_RESPONSE),
                  sizeof(DRIVION_INFO_COMMAND));
}
