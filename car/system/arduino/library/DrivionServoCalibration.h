// Lease loss returns to confirmed straight or disables servo pulses.
#pragma once
#include "DrivionCommunication.h"

namespace drivion {
class ServoCalibration {
public:
  enum Action : uint8_t {
    Begin = 0,
    Move = 1,
    MarkCenter = 2,
    End = 3,
    KeepAlive = 4,
    Disable = 5
  };
  ServoCalibration(uint16_t minimumUs, uint16_t maximumUs, uint16_t initialUs,
                   uint16_t stepUs, uint32_t timeoutMs, uint16_t pin)
      : minimum_(minimumUs), maximum_(maximumUs), pulse_(initialUs),
        initial_(initialUs), step_(stepUs), pin_(pin), timeout_(timeoutMs) {}
  bool latched() const { return latched_; }
  bool active() const { return active_; }
  bool outputEnabled() const { return output_; }
  uint16_t pulse() const { return pulse_; }
  // The last visually confirmed straight position is the only safe fallback.
  void stop() {
    active_ = false;
    output_ = haveCenter_ && !disabled_;
    if (haveCenter_)
      pulse_ = center_;
  }
  void poll(uint32_t now) {
    if (active_ && (now - lastUpdate_ >= timeout_ ||
                    communication::signed32(deadline_ - now) <= 0))
      stop();
  }
  communication::Result command(const uint8_t *payload, uint16_t size,
                                uint32_t now) {
    using namespace communication;
    poll(now); // A command arriving at expiry cannot revive the previous lease.
    if (size != 9)
      return BadPayload;
    const uint8_t action = payload[0];
    const uint16_t requested = get16(payload + 1);
    const uint32_t deadline = get32(payload + 3);
    // END and DISABLE must work even if the sender's lease has expired.
    if (action == End || action == Disable) {
      if (!latched_)
        return Busy;
      stop();
      if (action == Disable) {
        disabled_ = true;
        output_ = false;
      }
      return Ok;
    }
    uint8_t signature[14];
    put16(signature, pin_);
    put16(signature + 2, minimum_);
    put16(signature + 4, maximum_);
    put16(signature + 6, initial_);
    put16(signature + 8, step_);
    put32(signature + 10, timeout_);
    if (get16(payload + 7) != checksum(signature, sizeof(signature)))
      return BadPayload;
    if (action > Disable)
      return Unsupported;
    const int32_t remaining = signed32(deadline - now);
    if (remaining <= 0 || uint32_t(remaining) > timeout_)
      return Expired;
    if (action == Begin) {
      if (latched_)
        return Busy;
      // The start pulse is reported by the Pi's verified firmware snapshot.
      if (requested != initial_)
        return BadPayload;
      latched_ = active_ = true;
      output_ = false; // No motion until an explicit nudge.
    } else {
      if (!active_)
        return Busy; // Heartbeats/late packets cannot rearm an expired session.
      if (requested < minimum_ || requested > maximum_)
        return BadPayload;
      if (action == Move) {
        const uint16_t difference =
            requested > pulse_ ? requested - pulse_ : pulse_ - requested;
        if (difference > step_)
          return BadPayload;
        pulse_ = requested;
        output_ = true;
      } else if (action == MarkCenter) {
        if (!output_ || requested != pulse_)
          return BadPayload;
        center_ = pulse_;
        haveCenter_ = true;
      } else if (action == KeepAlive && requested != pulse_) {
        return BadPayload;
      }
    }
    lastUpdate_ = now;
    deadline_ = deadline;
    return Ok;
  }

private:
  uint16_t minimum_, maximum_, pulse_, initial_, step_, pin_, center_ = 0;
  uint32_t timeout_, lastUpdate_ = 0, deadline_ = 0;
  bool latched_ = false, active_ = false, output_ = false, haveCenter_ = false,
       disabled_ = false;
};
} // namespace drivion
