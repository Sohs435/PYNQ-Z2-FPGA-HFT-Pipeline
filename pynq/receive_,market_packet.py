import socket
import struct

LISTEN_IP = "0.0.0.0"
LISTEN_PORT = 5001

PACKET_FORMAT = "!4sBBBBIQIII"
PACKET_SIZE = struct.calcsize(PACKET_FORMAT)

EXPECTED_MAGIC = b"HFT1"
SUPPORTED_VERSION = 1

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind((LISTEN_IP, LISTEN_PORT))

print(f"Listening for {PACKET_SIZE}-byte market packets...")
print(f"UDP port: {LISTEN_PORT}")

while True:
    data, sender = sock.recvfrom(2048)

    if len(data) != PACKET_SIZE:
        print(
            f"Rejected packet from {sender}: "
            f"expected {PACKET_SIZE} bytes, received {len(data)}"
        )
        continue

    (
        magic,
        version,
        message_type,
        side,
        flags,
        sequence,
        timestamp_ns,
        instrument_id,
        price_ticks,
        quantity,
    ) = struct.unpack(PACKET_FORMAT, data)

    if magic != EXPECTED_MAGIC:
        print(f"Rejected packet: invalid magic {magic!r}")
        continue

    if version != SUPPORTED_VERSION:
        print(f"Rejected packet: unsupported version {version}")
        continue

    if side not in (0, 1):
        print(f"Rejected packet: invalid side {side}")
        continue

    side_name = "BID" if side == 0 else "ASK"
    price = price_ticks / 100

    print()
    print(f"Received packet from {sender}")
    print(f"Sequence:      {sequence}")
    print(f"Timestamp:     {timestamp_ns}")
    print(f"Message type:  {message_type}")
    print(f"Instrument ID: {instrument_id}")
    print(f"Side:          {side_name}")
    print(f"Price:         ${price:.2f}")
    print(f"Quantity:      {quantity}")
    print(f"Flags:         {flags}")
