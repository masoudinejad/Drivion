// Piecewise steering calibration and a wrap-safe, accepted-target watchdog.
#pragma once
#include <math.h>
#include <stdint.h>

namespace drivion {
struct SteeringSettings {
  float leftDeg, rightDeg, servoLeftDeg, servoCenterDeg, servoRightDeg;
  uint32_t timeoutMs;
  constexpr bool valid() const {
    return leftDeg > 0 && leftDeg <= 327.68f && rightDeg > 0 &&
           rightDeg <= 327.67f && servoLeftDeg >= 0 && servoLeftDeg <= 180 &&
           servoCenterDeg >= 0 && servoCenterDeg <= 180 && servoRightDeg >= 0 &&
           servoRightDeg <= 180 &&
           ((servoLeftDeg < servoCenterDeg && servoCenterDeg < servoRightDeg) ||
            (servoLeftDeg > servoCenterDeg &&
             servoCenterDeg > servoRightDeg)) &&
           timeoutMs > 0 && timeoutMs < 0x80000000UL;
  }
};

// Servo output is applied by the caller, keeping mapping testable without I/O.
class Steering {
public:
  Steering(const SteeringSettings &settings)
      : settings_(settings), angle_(settings.servoCenterDeg) {}
  void center() {
    angle_ = settings_.servoCenterDeg;
    active_ = false;
  }
  // Called only for a fresh, valid communication target. Clamp physical demand.
  void setAngle(int16_t centidegrees, uint32_t now) {
    const float degrees = centidegrees / 100.0f;
    setNormalized(degrees < 0 ? degrees / settings_.leftDeg
                              : degrees / settings_.rightDeg,
                  now);
  }
  void setNormalized(float value, uint32_t now) {
    if (!settings_.valid() || !isfinite(value)) {
      center();
      return;
    }
    value = value < -1 ? -1 : (value > 1 ? 1 : value);
    angle_ =
        settings_.servoCenterDeg +
        (value < 0
             ? -value * (settings_.servoLeftDeg - settings_.servoCenterDeg)
             : value * (settings_.servoRightDeg - settings_.servoCenterDeg));
    lastTargetAt_ = now;
    active_ = true;
  }
  void poll(uint32_t now) {
    if (active_ && now - lastTargetAt_ >= settings_.timeoutMs)
      center();
  }
  float angle() const { return angle_; }
  int pulseWidth(int minimumUs, int maximumUs) const {
    return int(minimumUs + angle_ * (maximumUs - minimumUs) / 180.0f + 0.5f);
  }

private:
  SteeringSettings settings_;
  float angle_;
  bool active_ = false;
  uint32_t lastTargetAt_ = 0;
};
} // namespace drivion
