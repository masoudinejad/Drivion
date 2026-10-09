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
char command[sizeof(DRIVION_INFO_COMMAND)];
size_t commandLength = 0;
bool discardCommand = false;

void readIdentityCommands() {
  // Bound work per loop so serial noise cannot starve the blink timer.
  for (size_t remaining = sizeof(command);
       remaining > 0 && Serial.available() > 0; --remaining) {
    const int incoming = Serial.read();
    if (incoming < 0) {
      break;
    }
    if (incoming == '\n') {
      if (!discardCommand) {
        command[commandLength] = '\0';
        drivion::handleInfo(Serial, command, DRIVION_INFO_COMMAND,
                            F(DRIVION_INFO_RESPONSE));
      }
      commandLength = 0;
      discardCommand = false;
    } else if (incoming != '\r' && !discardCommand) {
      if (commandLength + 1 < sizeof(command)) {
        command[commandLength++] = static_cast<char>(incoming);
      } else {
        // Reject the whole overlong line, never interpret its trailing bytes.
        discardCommand = true;
      }
    }
  }
}
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
  readIdentityCommands();
}
