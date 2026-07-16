# Phase 2.1 – UDP Communication

## Objective

Verify end-to-end UDP communication between the Windows host and the
PYNQ-Z2 over a direct Gigabit Ethernet connection.

## Host

- send_udp.py
- Sends a UDP packet containing the string "Hello FPGA".

## PYNQ

- receive_udp.py
- Listens on UDP port 5001.
- Prints the received payload.

## Verification

Expected output:

Host:

```text
Sent 10 bytes to 192.168.2.99:5001
```

PYNQ:

```text
Received 10 bytes from ('192.168.2.1', <port>)
Payload: Hello FPGA
```

## Outcome

Successful end-to-end UDP communication was established.

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

The host program:

1. Creates the market-data fields.
2. Encodes them into a 32-byte payload using `struct.pack()`.
3. Sends the payload to the PYNQ-Z2 using UDP.

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

### Received Output

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
Windows Python sender
        |
        | 32-byte UDP payload
        v
Direct Ethernet connection
        |
        v
PYNQ Linux network stack
        |
        v
Python packet validation and decoding
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
