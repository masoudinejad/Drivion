# Pi–Arduino communication

The Python module transports targets and application-provided reports. The
Arduino header provides the matching protocol implementation. Neither component
reads sensors, controls actuators, calibrates values, chooses driving modes, or
implements an arm/stop policy.

Speed is a signed integer in **mm/s** (forward positive). Steering is measured
from center, **right positive and left negative**. The Python API uses degrees;
the wire and Arduino interface use signed hundredths of a degree. Values are
representable ranges, not physical actuator limits.

## Pi usage

```python
from car.src.config import load_config
from car.src.communication import Communication, Fields

config = load_config()
with Communication.open(config.arduino.address, config.communication) as link:
    link.configure_reporting(100, Fields.SPEED | Fields.STEERING)
    request = link.request_values()
    # The application schedules fresh targets and calls poll frequently.
    link.set_target(250, -12.5)
    events = link.poll()
    # Snapshot events carry request_sequence; streaming reports carry None.
    # Values with unavailable validity bits are exposed as None.
    link.stop()
    # Continue polling to obtain the acknowledgement before closing if required.
```

`set_target` sends speed and steering atomically. The application decides target
frequency. There are no background threads, automatic motion retries, or
implicit reconnections. All operations must have one owner and be serialized.
`poll` reads at most `communication.read_budget_bytes`; call it often enough to
drain the serial link. Its read can wait up to `read_timeout_seconds`.

The client owns its transport. `open` selects the configured port, waits for
possible USB reset, and negotiates a session. `auto` requires exactly one port.
Firmware checks and flashing must first release the driving connection. Use an
injected `ByteTransport` and monotonic clock to test without hardware.

Commands return their uint16 request sequence. `Acknowledgement` events identify
the request and result. Successful drive targets do not generate acknowledgements;
periodic `Status.last_command_sequence` reports acceptance. An ACK confirms the
communication callback/request was processed, not actuator completion.

`latest_status`, `latest_values`, and `status_stale` provide monitoring. Reports
are explicitly application-provided values; a computed value is not relabeled
as a measurement. Their Arduino sample timestamp and Pi receipt timestamp have
different clock origins. Unavailable data is not equivalent to zero. The library
does not expire a sample automatically: applications determine sample freshness
from its acquisition timestamp and their own policy.

## Connection and reporting modes

A new random session starts through HELLO/WELCOME and emits `SessionChanged` on
the Arduino. The firmware application chooses how to react. Targets from another
session are discarded. STOP emits `StopRequested`; an expired target emits
`CommandTimeout` once and becomes inactive. The library performs no actuator I/O.
Closing on the Pi does not imply a STOP; active commands expire independently.

Reporting can be disabled with interval zero, requested on demand, or streamed
with a positive interval and selected fields. Essential status continues in all
reporting modes. On-demand snapshots include all available fields independently
of stream selection, and echo their request sequence. Streaming reports and
status have monotonic wrapping board sequences.

## Freshness and clock synchronization

HELLO/WELCOME establishes a board-clock estimate bounded conservatively by the
round-trip time. Target deadlines use the lower clock estimate, reduced by the
configured relative clock drift bound. The board rejects expired deadlines or
leases exceeding its configured command timeout. A target stays active only
until its deadline or watchdog timeout, whichever comes first. Malformed,
replayed, wrong-session, and unrelated messages never refresh its lease.

Call `synchronize()` before `max_session_age_seconds` or the clock uncertainty
budget expires. It refreshes the estimate within the same session, preserving
reports and targets. Its exchange pauses target transmission, so schedule it
with adequate lease margin. An excessive RTT fails negotiation; a silent peer
can wait until `handshake_timeout_seconds`, during which the board may time out.
Use `connect()` for an explicit fresh session after a peer reset or link failure.
Neither operation retries itself. A failed write/read invalidates the client
session; partial writes must never be treated as successful commands.

The central drift bound and timing budgets require hardware validation. The
current conservative defaults allow a short session estimate; synchronize
periodically. This is a local trusted cable protocol, not authentication or a
hard real-time guarantee. No software library can issue a timeout callback while
the firmware's entire main loop is stalled.

## Arduino library and firmware settings

Include `src/DrivionFirmware/DrivionCommunication.h` in a sketch compiled by the
existing firmware workflow. Instantiate `drivion::communication::Communication`
with a serial port, explicit `Settings`, event handler, and optional context.
The serial port provides `available`, `read`, `availableForWrite`, and
`write(byte)`; no blocking serial flush is used.

Supply reports through `publish(ReportedValues)` with an acquisition timestamp,
values, and validity mask. Callback events are `Target`, `StopRequested`,
`CommandTimeout`, and `SessionChanged`. Callbacks must be short and not reenter
the library. The application performs its control work separately.

The `communication_demo` sketch echoes accepted targets as reports, with no
motors or sensors. It invalidates reports on timeout/stop/session change. It also
answers the existing INFO identity query before the first binary delimiter.
After that transition it accepts binary messages only until reset, preventing
binary payloads from accidentally dispatching text commands. Management tools
that reopen/reset the classic Nano can query INFO again.

All deployment parameters are explicit:

- `[communication]` in `car/config.toml`: baud, serial timeouts, handshake and
  freshness budgets, clock drift, and Pi read budget; validated by Pydantic.
- `[firmware.communication_demo]`: command/frame timeouts, status interval,
  maximum report interval, and Arduino per-poll RX/TX budgets.
- `communication_demo/firmware.toml`: parameter requirements and bounds, board
  target, and firmware/protocol versions. The build generates their header macros.

The baud setting is shared by runtime, firmware-header generation, identity
checks, and flash verification. It moved from `tool.drivion.firmware_flash` to
`communication.baud_rate`; custom deployments must migrate that old entry.
Build manifests retain the actual baud used for their compiled artifact.
New sketches declare their own required settings and provide central values,
following the existing firmware structure. The library has no deployment defaults.

## Wire specification, version 1

Each frame is delimited by `0x7e`. Bytes `0x7e` and `0x7d` are encoded as `0x7d`
followed by the byte XOR `0x20`. All multibyte fields are little-endian; structs
are never copied as native memory layouts. The decoded maximum is 96 bytes.

| Envelope field | Representation |
| --- | --- |
| Version | uint8, currently 1 |
| Message type | uint8 |
| Session | nonzero uint32 |
| Sequence | uint16 |
| Payload length | uint16 |
| Payload | Exact length for the message type |
| Checksum | uint16 RFC 1662 FCS-16 over header and payload |

FCS uses initial `0xffff`, reflected polynomial `0x8408`, final XOR `0xffff`;
`123456789` produces `0x906e`. Corrupt, oversized, incomplete, wrong-version, or
length-inconsistent frames are discarded. Delimiters restore synchronization.

| ID | Message | Payload in wire order |
| --- | --- | --- |
| 1 | HELLO | Empty; sequence identifies negotiation |
| 2 | WELCOME | Board time, timeout, max interval, fields (see below) |
| 3 | DRIVE_TARGET | Speed, steering, expiry (see below) |
| 4 | STOP | Empty |
| 5 | SET_TELEMETRY | uint32 interval ms (0 disables), uint16 selected fields |
| 6 | GET_TELEMETRY | Empty |
| 7 | TELEMETRY | Sample time, speed, steering, validity (see below) |
| 8 | STATUS | Board time, active, last command, age (see below) |
| 9 | ACK | uint8 request type, uint8 result; echoes request sequence |
| 10 | SNAPSHOT | TELEMETRY layout; echoes GET_TELEMETRY sequence |

Detailed layouts in the listed order:

- WELCOME: uint32 board time ms, uint32 command timeout ms, uint32 maximum
  reporting interval ms, uint16 supported fields; echoes HELLO sequence.
- DRIVE_TARGET: int32 speed mm/s, int16 steering centidegrees, uint32 expiry ms
  in the board's wrapping clock domain.
- TELEMETRY/SNAPSHOT: uint32 sample time ms, int32 speed mm/s, int16 steering
  centidegrees, uint16 valid fields.
- STATUS: uint32 board time ms, uint8 command active, uint16 last accepted command
  sequence, uint32 command age ms.

Field mask: speed = 1, steering = 2. Result codes: OK = 0, BAD_PAYLOAD = 1,
UNSUPPORTED = 2, STALE = 3, EXPIRED = 4, BUSY = 5 (reserved for future use).
Before any accepted command, command age is `0xffffffff` and command-active is
false. A zero target is still an active command; it is not a STOP request.

Pi requests share one sequence space. A sequence is newer if its modular uint16
difference is in 1..32767. Duplicate/old requests return STALE, never reapply
commands. Same-session HELLO requires a new sequence and refreshes the clock;
a new-session HELLO clears command and stream state. Timers use wrapping uint32
milliseconds and intervals strictly below half-range.

The Arduino stores one bounded encoded TX frame and a 96-byte RX buffer. When
TX is pending, RX dispatch waits; watchdog checking continues every poll. RX/TX
work is capped by central parameters. Status and reporting are best effort and
never queued as an unbounded backlog. The application must poll fast enough for
the board's hardware serial buffers and select sustainable report intervals.
At 115200 8N1 the theoretical throughput is 11520 bytes/s in each direction;
50 target frames/s and 10 report frames/s leave substantial wire headroom, but
hardware tests must check actual loop scheduling and serial-buffer overruns.

New optional messages use new IDs; unsupported requests receive UNSUPPORTED.
Major layout/semantic changes require a new protocol version. Firmware identity
and protocol version are separate concepts. Additional fields need a documented
layout/capability extension rather than arbitrary untyped payloads. The transport
boundary allows future alternatives, which must define their own framing rules.

## Validation

Tests cover framing/FCS, malformed and partial frames, sign conventions, session
and sequence handling, deadlines, rollover, reporting modes, and client failures.
A native C++ harness runs the real Arduino header with Python-generated frames.
An optional Arduino CLI test compiles the complete demo for the Nano without
uploading. Hardware validation still needs USB reset/reconnect, actual clock
drift, serial throughput, and integration with the application's stop policy.
