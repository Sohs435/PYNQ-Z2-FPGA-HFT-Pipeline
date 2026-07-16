# Market-Data Packet Format

## Overview

The project uses a fixed-length binary UDP payload for transferring synthetic
market-data updates from the host laptop to the PYNQ-Z2.

The format is designed for simple and deterministic FPGA parsing.

All multi-byte integer fields use **big-endian network byte order**.

The total UDP payload length is 32 bytes

## Packet Layout

| Byte Offset | Field | Width | Description |
|---:|---|---:|---|
| `0–3` | Magic/Protocol ID | 4 bytes | ASCII identifier `HFT1` |
| `4` | Version | 1 byte | Protocol version |
| `5` | Message Type | 1 byte | Type of market-data message |
| `6` | Side | 1 byte | `0 = BID`, `1 = ASK` |
| `7` | Flags | 1 byte | Reserved for future use |
| `8–11` | Sequence Number | 4 bytes | Packet ordering and loss detection |
| `12–19` | Timestamp | 8 bytes | Host timestamp in nanoseconds |
| `20–23` | Instrument ID | 4 bytes | Numeric instrument identifier |
| `24–27` | Price | 4 bytes | Price represented as integer ticks |
| `28–31` | Quantity | 4 bytes | Number of shares or contracts |

## Field Definitions

### Magic / Protocol ID

The first four bytes must contain:

```text
HFT1
```

Hexadecimal representation:

```text
8'h48 8'h46 8'h54 8'h31
```

Packets with an incorrect magic value must be rejected.

### Version

Current protocol version:

```text
1
```

A future incompatible packet format should increment this value.

### Message Type

| Value | Meaning |
|---:|---|
| `1` | Quote update |
| `2` | Trade |
| `3` | Heartbeat |

The initial implementation only supports quote updates.

### Side

| Value | Meaning |
|---:|---|
| `0` | Bid |
| `1` | Ask |

### Flags

The flags field is currently set to zero.

Possible future definitions include:

| Bit | Meaning |
|---:|---|
| `0` | Snapshot message |
| `1` | End of message batch |
| `2` | Synthetic test message |

### Sequence Number

The sequence number increments for every transmitted packet.

Example:

```text
1, 2, 3, 4, 5
```

If the receiver observes:

```text
1, 2, 4
```

then packet `3` was lost or rejected.

### Timestamp

The host generates the timestamp using:

```python
time.time_ns()
```

The timestamp is primarily used for logging during the software-development
phases.

It is not yet a precise end-to-end latency measurement because the host and
PYNQ clocks are not synchronized.

### Instrument ID

Symbols are represented by numeric identifiers rather than variable-length
strings.

| Instrument ID | Symbol |
|---:|---|
| `1` | AAPL |
| `2` | MSFT |
| `3` | GOOGL |

Numeric identifiers simplify FPGA comparison logic.

### Price

Prices are transmitted as unsigned integer ticks rather than floating-point
values.

The initial tick size is:

```text
1 tick = $0.01
```

Examples:

| Display Price | Packet Value |
|---:|---:|
| `$185.25` | `18525` |
| `$100.07` | `10007` |
| `$1.00` | `100` |

### Quantity

Quantity is transmitted as an unsigned 32-bit integer representing shares or
contracts.

## Python Struct Format

The Python format string is:

```python
PACKET_FORMAT = "!4sBBBBIQIII"
```

| Symbol | Meaning |
|---|---|
| `!` | Big-endian network byte order |
| `4s` | Four-byte magic value |
| `B` | Unsigned 8-bit integer |
| `I` | Unsigned 32-bit integer |
| `Q` | Unsigned 64-bit integer |

The packet size can be verified using:

```python
import struct

PACKET_FORMAT = "!4sBBBBIQIII"
PACKET_SIZE = struct.calcsize(PACKET_FORMAT)

assert PACKET_SIZE == 32
```

## Example Packet

Example market-data update:

```text
Magic:          HFT1
Version:        1
Message Type:   Quote update
Side:           Bid
Sequence:       15
Instrument:     AAPL
Price:          $185.25
Quantity:       100
```

Encoded field values:

```text
Magic:          b"HFT1"
Version:        1
Message Type:   1
Side:           0
Flags:          0
Sequence:       15
Instrument ID:  1
Price Ticks:    18525
Quantity:       100
```

## Validation Rules

A receiver must reject a packet when:

- Its length is not exactly 32 bytes.
- Its magic value is not `HFT1`.
- Its version is unsupported.
- Its message type is unsupported.
- Its side is not `0` or `1`.
- Its sequence number is invalid or unexpected.
