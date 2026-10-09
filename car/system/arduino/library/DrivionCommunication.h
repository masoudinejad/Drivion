// Versioned serial framing and application-independent target/report exchange.
#pragma once
#include <Arduino.h>
#include <stdint.h>
#include <string.h>

namespace drivion {
namespace communication {
// Wire constants: changing these changes the protocol, not a deployment
// setting.
constexpr uint8_t Version = 1, Flag = 0x7e, Escape = 0x7d;
constexpr size_t MaxFrame = 96, HeaderSize = 10, MaxEncoded = 2 * MaxFrame + 2;
enum Message : uint8_t {
  Hello = 1,
  Welcome = 2,
  DriveTarget = 3,
  Stop = 4,
  SetTelemetry = 5,
  GetTelemetry = 6,
  Telemetry = 7,
  Status = 8,
  Ack = 9,
  Snapshot = 10
};
enum Result : uint8_t {
  Ok = 0,
  BadPayload = 1,
  Unsupported = 2,
  Stale = 3,
  Expired = 4,
  Busy = 5
};
enum Field : uint16_t { Speed = 1, Steering = 2, AllFields = Speed | Steering };
enum class Event : uint8_t {
  Target,
  StopRequested,
  CommandTimeout,
  SessionChanged
};

struct Settings {
  uint32_t commandTimeoutMs, frameTimeoutMs, statusIntervalMs,
      maxTelemetryIntervalMs;
  uint16_t rxBudgetBytes, txBudgetBytes;
  constexpr bool valid() const {
    return commandTimeoutMs && commandTimeoutMs < 0x80000000UL &&
           frameTimeoutMs && frameTimeoutMs < 0x80000000UL &&
           statusIntervalMs && statusIntervalMs < 0x80000000UL &&
           maxTelemetryIntervalMs && maxTelemetryIntervalMs < 0x80000000UL &&
           rxBudgetBytes && txBudgetBytes;
  }
};
struct Target {
  int32_t speedMmS;
  int16_t steeringCentidegrees; // Center zero, right positive, left negative.
  uint16_t sequence;
};
struct ReportedValues {
  uint32_t sampleTimeMs;
  int32_t speedMmS;
  int16_t steeringCentidegrees;
  uint16_t validFields;
};
using Handler = void (*)(void *context, Event event, const Target &target);

inline void put16(uint8_t *p, uint16_t v) {
  p[0] = v;
  p[1] = v >> 8;
}
inline void put32(uint8_t *p, uint32_t v) {
  put16(p, v);
  put16(p + 2, v >> 16);
}
inline uint16_t get16(const uint8_t *p) {
  return uint16_t(p[0]) | (uint16_t(p[1]) << 8);
}
inline uint32_t get32(const uint8_t *p) {
  return uint32_t(get16(p)) | (uint32_t(get16(p + 2)) << 16);
}
inline int32_t signed32(uint32_t v) {
  return v <= INT32_MAX ? int32_t(v) : -1 - int32_t(UINT32_MAX - v);
}
inline int16_t signed16(uint16_t v) {
  return v <= INT16_MAX ? int16_t(v) : -1 - int16_t(UINT16_MAX - v);
}
inline bool newer(uint16_t value, uint16_t previous) {
  const uint16_t delta = value - previous;
  return delta && delta < 0x8000;
}
inline uint16_t checksum(const uint8_t *data, size_t size) {
  uint16_t crc = 0xffff;
  while (size--) {
    crc ^= *data++;
    for (uint8_t bit = 0; bit < 8; ++bit)
      crc = (crc >> 1) ^ ((crc & 1) ? 0x8408 : 0);
  }
  return crc ^ 0xffff;
}

// SerialPort must expose read(), available(), availableForWrite(), and
// write(byte). It is deliberately templated rather than Stream: Stream has no
// TX-capacity API.
template <typename SerialPort> class Communication {
public:
  Communication(SerialPort &serial, const Settings &settings, Handler handler,
                void *context)
      : serial_(serial), settings_(settings), handler_(handler),
        context_(context) {}

  bool begin() {
    enabled_ = settings_.valid() && handler_ != nullptr;
    return enabled_;
  }
  bool commandActive() const { return commandActive_; }
  uint32_t session() const { return session_; }
  uint32_t rejectedFrames() const { return rejectedFrames_; }
  const Target &target() const { return target_; }

  // The application supplies values and their acquisition timestamp. No sensor
  // I/O.
  bool publish(const ReportedValues &values) {
    if (values.validFields & ~AllFields)
      return false;
    values_ = values;
    return true;
  }

  // Invoke frequently from loop(); callbacks must be short and must not
  // reenter.
  void poll(uint32_t now) {
    if (!enabled_)
      return;
    if (commandActive_ && (now - lastCommandAt_ >= settings_.commandTimeoutMs ||
                           signed32(commandDeadline_ - now) <= 0)) {
      commandActive_ = false;
      notify(Event::CommandTimeout);
    }
    if (rxActive_ && (rxSize_ || escaped_ || discard_) &&
        now - rxStarted_ >= settings_.frameTimeoutMs) {
      resetRx(now);
      rxActive_ = false;
      ++rejectedFrames_;
    }
    uint16_t txBudget = settings_.txBudgetBytes;
    flushTx(txBudget);
    // Preserve response order with a single bounded TX frame. No blocking
    // writes.
    if (txSize_)
      return;
    for (uint16_t budget = settings_.rxBudgetBytes;
         budget && serial_.available(); --budget) {
      const int byte = serial_.read();
      if (byte < 0)
        break;
      receive(uint8_t(byte), now);
      if (txSize_)
        break;
    }
    if (!txSize_ && session_ &&
        now - lastStatusAt_ >= settings_.statusIntervalMs) {
      uint8_t payload[11];
      put32(payload, now);
      payload[4] = commandActive_ ? 1 : 0;
      put16(payload + 5, target_.sequence);
      put32(payload + 7, haveCommand_ ? now - lastCommandAt_ : UINT32_MAX);
      send(Status, outboundSequence_++, payload, sizeof(payload));
      lastStatusAt_ = now;
    } else if (!txSize_ && session_ && telemetryInterval_ &&
               now - lastTelemetryAt_ >= telemetryInterval_) {
      sendValues();
      lastTelemetryAt_ = now;
    }
    flushTx(txBudget);
  }

private:
  SerialPort &serial_;
  Settings settings_;
  Handler handler_;
  void *context_;
  bool enabled_ = false, commandActive_ = false, haveCommand_ = false;
  uint32_t session_ = 0, lastCommandAt_ = 0, commandDeadline_ = 0;
  uint32_t lastStatusAt_ = 0, lastTelemetryAt_ = 0, telemetryInterval_ = 0;
  uint16_t telemetryFields_ = AllFields, outboundSequence_ = 0;
  uint16_t lastRequest_ = 0;
  bool haveRequest_ = false;
  Target target_{};
  ReportedValues values_{};
  uint8_t rx_[MaxFrame]{}, tx_[MaxEncoded]{};
  size_t rxSize_ = 0, txSize_ = 0, txOffset_ = 0;
  bool rxActive_ = false, escaped_ = false, discard_ = false;
  uint32_t rxStarted_ = 0, rejectedFrames_ = 0;

  void notify(Event event) { handler_(context_, event, target_); }
  void resetRx(uint32_t now) {
    rxSize_ = 0;
    escaped_ = discard_ = false;
    rxStarted_ = now;
  }
  void receive(uint8_t byte, uint32_t now) {
    if (byte == Flag) {
      if (rxActive_ && (rxSize_ || escaped_ || discard_))
        dispatch(now);
      resetRx(now);
      rxActive_ = true;
      return;
    }
    if (!rxActive_ || discard_)
      return;
    if (byte == Escape && !escaped_) {
      escaped_ = true;
      return;
    }
    if (escaped_) {
      byte ^= 0x20;
      escaped_ = false;
    }
    if (rxSize_ == MaxFrame) {
      discard_ = true;
      return;
    }
    if (!rxSize_)
      rxStarted_ = now;
    rx_[rxSize_++] = byte;
  }
  void dispatch(uint32_t now) {
    if (discard_ || escaped_ || rxSize_ < HeaderSize + 2 || rx_[0] != Version ||
        get16(rx_ + 8) != rxSize_ - HeaderSize - 2 ||
        checksum(rx_, rxSize_ - 2) != get16(rx_ + rxSize_ - 2)) {
      ++rejectedFrames_;
      return;
    }
    const uint8_t type = rx_[1];
    const uint32_t session = get32(rx_ + 2);
    const uint16_t sequence = get16(rx_ + 6), size = get16(rx_ + 8);
    const uint8_t *payload = rx_ + HeaderSize;
    if (type == Hello) {
      if (!session || size)
        return;
      if (session == session_) {
        if (haveRequest_ && !newer(sequence, lastRequest_))
          return;
      } else {
        session_ = session;
        commandActive_ = haveCommand_ = false;
        target_ = Target{};
        telemetryInterval_ = 0;
        telemetryFields_ = AllFields;
        outboundSequence_ = 0;
        lastStatusAt_ = lastTelemetryAt_ = now;
        notify(Event::SessionChanged);
      }
      haveRequest_ = true;
      lastRequest_ = sequence;
      uint8_t reply[14];
      put32(reply, now);
      put32(reply + 4, settings_.commandTimeoutMs);
      put32(reply + 8, settings_.maxTelemetryIntervalMs);
      put16(reply + 12, AllFields);
      send(Welcome, sequence, reply, sizeof(reply));
      return;
    }
    if (!session_ || session != session_)
      return;
    if (haveRequest_ && !newer(sequence, lastRequest_)) {
      acknowledge(type, sequence, Stale);
      return;
    }
    // Sequence consumption prevents replay of rejected or malformed requests.
    haveRequest_ = true;
    lastRequest_ = sequence;
    switch (type) {
    case DriveTarget: {
      if (size != 10) {
        acknowledge(type, sequence, BadPayload);
        return;
      }
      const uint32_t deadline = get32(payload + 6);
      const int32_t remaining = signed32(deadline - now);
      if (remaining <= 0 || uint32_t(remaining) > settings_.commandTimeoutMs) {
        acknowledge(type, sequence, Expired);
        return;
      }
      target_ = Target{signed32(get32(payload)), signed16(get16(payload + 4)),
                       sequence};
      lastCommandAt_ = now;
      commandDeadline_ = deadline;
      commandActive_ = haveCommand_ = true;
      notify(Event::Target);
      return; // Status reports acceptance; motion commands are never retried.
    }
    case Stop:
      if (size) {
        acknowledge(type, sequence, BadPayload);
        return;
      }
      commandActive_ = false;
      notify(Event::StopRequested);
      acknowledge(type, sequence, Ok);
      return;
    case SetTelemetry:
      if (size != 6) {
        acknowledge(type, sequence, BadPayload);
        return;
      }
      if (get32(payload) > settings_.maxTelemetryIntervalMs ||
          (get16(payload + 4) & ~AllFields) ||
          (get32(payload) && !get16(payload + 4))) {
        acknowledge(type, sequence, BadPayload);
        return;
      }
      telemetryInterval_ = get32(payload);
      telemetryFields_ = get16(payload + 4);
      lastTelemetryAt_ = now;
      acknowledge(type, sequence, Ok);
      return;
    case GetTelemetry:
      if (size) {
        acknowledge(type, sequence, BadPayload);
        return;
      }
      sendValues(true, sequence);
      return;
    default:
      acknowledge(type, sequence, Unsupported);
    }
  }
  void acknowledge(uint8_t type, uint16_t sequence, Result result) {
    const uint8_t payload[] = {type, uint8_t(result)};
    send(Ack, sequence, payload, sizeof(payload));
  }
  void sendValues(bool requested = false, uint16_t requestSequence = 0) {
    uint8_t payload[12];
    put32(payload, values_.sampleTimeMs);
    put32(payload + 4, uint32_t(values_.speedMmS));
    put16(payload + 8, uint16_t(values_.steeringCentidegrees));
    put16(payload + 10,
          values_.validFields & (requested ? AllFields : telemetryFields_));
    send(requested ? Snapshot : Telemetry,
         requested ? requestSequence : outboundSequence_++, payload,
         sizeof(payload));
  }
  void send(uint8_t type, uint16_t sequence, const uint8_t *payload,
            uint16_t size) {
    if (txSize_ || size > MaxFrame - HeaderSize - 2)
      return;
    uint8_t frame[MaxFrame];
    frame[0] = Version;
    frame[1] = type;
    put32(frame + 2, session_);
    put16(frame + 6, sequence);
    put16(frame + 8, size);
    memcpy(frame + HeaderSize, payload, size);
    const size_t length = HeaderSize + size + 2;
    put16(frame + length - 2, checksum(frame, length - 2));
    txOffset_ = 0;
    tx_[txSize_++] = Flag;
    for (size_t i = 0; i < length; ++i) {
      if (frame[i] == Flag || frame[i] == Escape) {
        tx_[txSize_++] = Escape;
        tx_[txSize_++] = frame[i] ^ 0x20;
      } else
        tx_[txSize_++] = frame[i];
    }
    tx_[txSize_++] = Flag;
  }
  void flushTx(uint16_t &budget) {
    while (budget && txOffset_ < txSize_ && serial_.availableForWrite() > 0) {
      if (serial_.write(tx_[txOffset_]) != 1)
        break;
      ++txOffset_;
      --budget;
    }
    if (txOffset_ == txSize_)
      txOffset_ = txSize_ = 0;
  }
};
} // namespace communication
} // namespace drivion
