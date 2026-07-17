# Phase 2 — UDP and Binary Market-Data Communication

## Phase 2.1 — UDP Hello World

### Objective

Verify end-to-end UDP communication between the Windows host and the
PYNQ-Z2 over a direct Gigabit Ethernet connection.

### Host Implementation

- `send_udp.py`
- Sends a UDP packet containing the string `"Hello FPGA"`.

### PYNQ Implementation

- `receive_udp.py`
- Listens on UDP port `5001`.
- Prints the received payload.

### Verification

Host:

```text
Sent 10 bytes to 192.168.2.99:5001
```

PYNQ:

```text
Received 10 bytes from ('192.168.2.1', <port>)
Payload: Hello FPGA
```

### Outcome

Successful end-to-end UDP communication was established.

## Phase 2.2 — Market-Data Packet Design

### Overview

The project uses a fixed-length binary UDP payload for transferring synthetic
market-data updates from the host laptop to the PYNQ-Z2.

The format is designed for simple and deterministic FPGA parsing.

All multi-byte integer fields use **big-endian network byte order**.

The total UDP payload length is 32 bytes.

### Packet Layout

| Byte Offset | Field | Width | Description |
|---:|---|---:|---|
| `0–3` | Magic / Protocol ID | 4 bytes | ASCII identifier `HFT1` |
| `4` | Version | 1 byte | Protocol version |
| `5` | Message Type | 1 byte | Type of market-data message |
| `6` | Side | 1 byte | `0 = BID`, `1 = ASK` |
| `7` | Flags | 1 byte | Reserved for future use |
| `8–11` | Sequence Number | 4 bytes | Packet ordering and loss detection |
| `12–19` | Timestamp | 8 bytes | Host timestamp in nanoseconds |
| `20–23` | Instrument ID | 4 bytes | Numeric instrument identifier |
| `24–27` | Price | 4 bytes | Price represented as integer ticks |
| `28–31` | Quantity | 4 bytes | Number of shares or contracts |

### Field Definitions

#### Magic / Protocol ID

The first four bytes must contain:

```text
HFT1
```

Hexadecimal representation:

```text
8'h48 8'h46 8'h54 8'h31
```

Packets with an incorrect magic value must be rejected.

#### Version

Current protocol version:

```text
1
```

A future incompatible packet format should increment this value.

#### Message Type

| Value | Meaning |
|---:|---|
| `1` | Quote update |
| `2` | Trade |
| `3` | Heartbeat |

The initial implementation only supports quote updates.

#### Side

| Value | Meaning |
|---:|---|
| `0` | Bid |
| `1` | Ask |

#### Flags

The flags field is currently set to zero.

Possible future definitions include:

| Bit | Meaning |
|---:|---|
| `0` | Snapshot message |
| `1` | End of message batch |
| `2` | Synthetic test message |

#### Sequence Number

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

#### Timestamp

The host generates the timestamp using:

```python
time.time_ns()
```

The timestamp is primarily used for logging during the software-development
phases.

It is not yet a precise end-to-end latency measurement because the host and
PYNQ clocks are not synchronized.

#### Instrument ID

Symbols are represented by numeric identifiers rather than variable-length
strings.

| Instrument ID | Symbol |
|---:|---|
| `1` | AAPL |
| `2` | MSFT |
| `3` | GOOGL |

Numeric identifiers simplify FPGA comparison logic.

#### Price

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

#### Quantity

Quantity is transmitted as an unsigned 32-bit integer representing shares or
contracts.

### Python Struct Format

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

### Example Packet

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

### Validation Rules

A receiver must reject a packet when:

- Its length is not exactly 32 bytes.
- Its magic value is not `HFT1`.
- Its version is unsupported.
- Its message type is unsupported.
- Its side is not `0` or `1`.
- Its sequence number is invalid or unexpected.

## Phase 2.3 — Binary Packet Transmission and Decoding

### Objective

Transmit one fixed-length binary market-data packet from the Windows host to
the PYNQ-Z2 and verify that every field is decoded correctly.

### Implementation

Two Python programs were used:

```text
host/send_market_packet.py
pynq/receive_market_packet.py
```

#### Host Sender

The host program:

1. Creates the market-data fields.
2. Encodes them into a 32-byte payload using `struct.pack()`.
3. Sends the payload to the PYNQ-Z2 using UDP.

#### PYNQ Receiver

The PYNQ program:

1. Listens on UDP port `5001`.
2. Checks that the received payload is exactly 32 bytes.
3. Decodes the fields using `struct.unpack()`.
4. Validates the protocol identifier, version and side.
5. Prints the decoded market-data update.

### Network Configuration

| Device | IPv4 Address | Role |
|---|---|---|
| Windows host | `192.168.2.1` | Packet sender |
| PYNQ-Z2 | `192.168.2.99` | Packet receiver |

UDP destination port:

```text
5001
```

### Running the Receiver

On the PYNQ-Z2:

```bash
python3 receive_market_packet.py
```

Expected startup output:

```text
Listening for 32-byte market packets...
UDP port: 5001
```

The receiver must remain running while the host sends the packet.

### Running the Sender

From the `host` directory on Windows:

```powershell
python .\send_market_packet.py
```

### Host Output

The host successfully transmitted one 32-byte packet:

```text
Sent 32 bytes to 192.168.2.99:5001
Packet: 48 46 54 31 01 01 00 00 00 00 00 01 18 c2 dd f6 c9 cf 74 60 00 00 00 01 00 00 48 5d 00 00 00 64
```

### PYNQ Output

The PYNQ-Z2 successfully received and decoded the packet:

```text
Received packet from ('192.168.2.1', 53433)
Sequence:      1
Timestamp:     1784232454409647200
Message type:  1
Instrument ID: 1
Side:          BID
Price:         $185.25
Quantity:      100
Flags:         0
```

The source UDP port is selected automatically by the host operating system and
may be different each time the sender is executed.

### Packet Verification

The transmitted hexadecimal payload can be separated into fields as follows:

| Bytes | Decoded value |
|---|---|
| `48 46 54 31` | Protocol identifier `HFT1` |
| `01` | Protocol version `1` |
| `01` | Message type `1`, quote update |
| `00` | Side `0`, bid |
| `00` | Flags `0` |
| `00 00 00 01` | Sequence number `1` |
| `18 c2 dd f6 c9 cf 74 60` | 64-bit host timestamp |
| `00 00 00 01` | Instrument ID `1` |
| `00 00 48 5d` | Price value `18525` ticks |
| `00 00 00 64` | Quantity `100` |

With a tick size of one cent:

```text
18525 ticks = $185.25
```

### Result

The complete software packet path was successfully verified:

```text
Windows Python sender -> Direct Ethernet connection -> PYNQ Linux network stack -> Python packet validation and decoding
```

This confirms that:

- Binary packet packing and unpacking use the same byte order.
- All field offsets match the packet specification.
- The direct Ethernet connection transfers binary UDP payloads correctly.
- The receiver can validate and decode the market-data fields.
- The packet format is ready for continuous packet generation.

### Current Limitation

The packet is currently decoded by Python running on the Zynq processing
system.

The programmable logic is not yet processing the packet. A later phase will
transfer packet data from processing-system memory into the programmable logic
using AXI DMA.

### Next Step

The next stage is continuous market-data generation.

The sender will generate multiple packets while changing:

- Sequence number
- Timestamp
- Bid or ask side
- Price
- Quantity

The receiver will check sequence continuity and report missing or unexpected
packets.

## Phase 2.4 — Continuous Market-Data Streaming and Throughput Testing

### Objective

Extend the single-packet test from Phase 2.3 into a continuous stream of
synthetic market-data updates and measure the sustainable packet-processing
rate of the PYNQ-Z2 Python receiver.

The test must detect:

- Missing packets
- Invalid packets
- Duplicate packets
- Out-of-order packets
- A receive rate below the requested transmit rate

### Implementation

Two Python programs were used:

```text
host/send_market_stream.py
pynq/receive_market_stream.py
```

#### Host Stream Generator

The host program:

1. Accepts a target packet rate and test duration.
2. Generates continuously changing market-data updates.
3. Increments the sequence number for every packet.
4. Updates the timestamp, side, price and quantity fields.
5. Encodes each update using the 32-byte packet format from Phase 2.2.
6. Sends the packets to UDP port `5001` on the PYNQ-Z2.
7. Sends test metadata so the receiver knows the expected number of packets.

Example sender command:

```powershell
python .\send_market_stream.py --pps 7500 --duration 10
```

#### PYNQ Stream Receiver

The PYNQ program:

1. Receives each UDP payload.
2. Confirms that the payload is exactly 32 bytes.
3. Decodes it using `struct.unpack()`.
4. Validates the magic value, version, message type and side.
5. Tracks every sequence number.
6. Detects missing, duplicate and out-of-order packets.
7. Measures and prints the live receive rate once per second.
8. Produces a final integrity and throughput report.

### Running the Receiver

On the PYNQ-Z2:

```bash
python3 receive_market_stream.py
```

Expected startup output:

```text
Listening for 32-byte market packets...
UDP port: 5001
UDP receive buffer: 8,388,608 bytes
```

### Running the Sender

From the `host` directory on Windows:

```powershell
python .\send_market_stream.py --pps 7500 --duration 10
```

This command sends:

```text
7,500 packets/s × 10 seconds = 75,000 packets
```

### Pass Criteria

A stream test passes only when:

```text
Missing packets:       0
Invalid packets:       0
Duplicate packets:     0
Out-of-order packets:  0
Packet error rate:     0.000000%
Result:                PASS
```

The live and average receive rates must also remain close to the requested
transmit rate. A zero-loss result after a long queue-draining delay would not
represent real-time operation.

### Initial Receive-Buffer Limitation

The receiver initially requested a 4 MiB UDP receive buffer:

```python
sock.setsockopt(
    socket.SOL_SOCKET,
    socket.SO_RCVBUF,
    4 * 1024 * 1024,
)
```

However, the Linux kernel limited the actual socket buffer to:

```text
360,448 bytes
```

At 7,500 packets/s, a short receiver stall overflowed this buffer and caused
approximately 260 missing packets.

The temporary kernel limit was increased using:

```bash
sudo sysctl -w net.core.rmem_max=8388608
```

After restarting the receiver, Linux reported:

```text
UDP receive buffer: 8,388,608 bytes
```

Linux reports twice the requested size because it includes internal socket
bookkeeping in the displayed value.

### Benchmark Results

| Target Rate | Duration | Valid Packets | Missing Packets | Error Rate | Result |
|---:|---:|---:|---:|---:|:---:|
| `5,000 pps` | `10 s` | `50,000` | `0` | `0.000000%` | PASS |
| `6,000 pps` | `10 s` | `60,000` | `0` | `0.000000%` | PASS |
| `7,000 pps` | `10 s` | `70,000` | `0` | `0.000000%` | PASS |
| `7,500 pps`, small buffer | `10 s` | `74,737` | `263` | `0.350667%` | FAIL |
| `7,500 pps`, enlarged buffer | `10 s` | `75,000` | `0` | `0.000000%` | PASS |
| `7,800 pps`, small buffer | `10 s` | `77,631` | `369` | `0.473077%` | FAIL |
| `7,900 pps`, small buffer | `10 s` | `78,619` | `381` | `0.482278%` | FAIL |
| `8,000 pps` | `10 s` | `79,744` | `256` | `0.320000%` | FAIL |
| `10,000 pps` | `100 s` | `671,483` | `328,517` | `32.851700%` | FAIL |

The enlarged-buffer 7,500 packets/s test produced:

```text
Packets sent:          75,000
Valid unique packets:  75,000
Missing packets:       0
Invalid packets:       0
Duplicate packets:     0
Out-of-order packets:  0
Measured duration:     10.022 s
Average receive rate:  7,484 pps
Packet error rate:     0.000000%
Result:                PASS
```

The larger buffer absorbed a short processing stall and prevented packet loss.
The extra 22 ms shows that a small temporary backlog still occurred.

Testing at 8,000 packets/s remained unreliable, while 10,000 packets/s caused
continuous overload. The current receiver was therefore capped at:

```text
7,500 packets/s
```

### Throughput Analysis

A 32-byte UDP update occupies approximately 98 bytes on the physical Ethernet
link after including Ethernet, IPv4, UDP, preamble, frame-check and inter-frame
overheads.

At the selected rate:

```text
7,500 × 98 × 8 = 5.88 Mbit/s
```

Even the failed 10,000 packets/s test used only approximately:

```text
10,000 × 98 × 8 = 7.84 Mbit/s
```

Both rates are far below the 1 Gbit/s Ethernet link capacity. The physical link
is therefore not the bottleneck.

### Bottleneck

The current receive path performs the following operations for every packet:

```text
Linux receives UDP packet
        ↓
Packet enters socket receive buffer
        ↓
Python calls recvfrom()
        ↓
Python decodes the packet using struct.unpack()
        ↓
Python validates fields and sequence number
        ↓
Python updates statistics
```

At 10,000 packets/s, the receiver processed an average of approximately 6,714
packets/s during the 100-second test. The socket queue therefore grew until it
became full and Linux discarded incoming packets.

Increasing the receive buffer can absorb short bursts, but it cannot correct a
sustained difference between the arrival rate and processing rate.

The limiting factor is the Linux/Python per-packet processing path on the ARM
processor, not Ethernet bandwidth.

### Monitoring Commands

UDP receive errors can be inspected using:

```bash
netstat -su
```

Ethernet interface errors and drops can be inspected using:

```bash
ip -s link show eth0
```

The receiver process can be found using:

```bash
pgrep -af receive_market_stream.py
```

Its CPU usage can then be monitored using:

```bash
top -p <PID>
```

### Final Endurance Test

The selected 7,500 packets/s cap can be validated over 100 seconds using:

```powershell
python .\send_market_stream.py --pps 7500 --duration 100
```

This test sends 750,000 market-data packets. It passes only if every packet is
received and the measured duration remains close to 100 seconds.

### Result

Phase 2.4 successfully established continuous binary market-data communication
between the Windows host and PYNQ-Z2.

The receiver correctly detected packet loss, duplicates, invalid packets and
ordering errors while measuring the live processing rate.

The maximum configured rate for the current Python implementation is:

```text
7,500 packets/s
```

This result provides a measured processing-system baseline for comparison with
the later FPGA implementation.

### Current Limitation

The market-data packets are still received and decoded by Python on the Zynq
processing system. The programmable logic does not yet parse or process the
packets.

### Next Step

The next phase will use AXI DMA to transfer data between the processing system
and programmable logic. This will verify the PS-to-PL streaming path before the
Ethernet, IPv4 and UDP parsing logic is moved into FPGA hardware.
