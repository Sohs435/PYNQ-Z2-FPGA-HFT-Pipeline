import socket
import struct

# accept packet arriving from any IP on any of PYNQ's network interfaces 
LISTEN_IP = "0.0.0.0"
LISTEN_PORT = 5001

# Packet will be 32 bytes with 4 for Protocol ID at the front (MSBS) and 1 for quantity at the back (LSB) with others in between \
# Big endien obv 
# sender and receiver both have same packet format 
PACKET_FORMAT = "!4sBBBBIQIII"
PACKET_SIZE = struct.calcsize(PACKET_FORMAT)

# requires for protocol ID to be HFT1 to accept the packet
EXPECTED_MAGIC = b"HFT1"
SUPPORTED_VERSION = 1

# IPV4 UDP socket with packet sent from LISTEN_IP to port LISTEN_PORT via bind operation
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind((LISTEN_IP, LISTEN_PORT))

print(f"Listening for {PACKET_SIZE}-byte market packets...")
print(f"UDP port: {LISTEN_PORT}")

# receiver runs indefinitely recvfrom pauses until UDP packet arrives
while True:
    data, sender = sock.recvfrom(2048)

    # only accepts 32 byte payload/packet
    if len(data) != PACKET_SIZE:
        print(
            f"Rejected packet from {sender}: "
            f"expected {PACKET_SIZE} bytes, received {len(data)}"
        )
        continue

    # re seperates bytes 
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

    # reject packet if protocol ID is incorrect
    if magic != EXPECTED_MAGIC:
        print(f"Rejected packet: invalid magic {magic!r}")
        continue

    # reject packet if version incorrect as interpretation of it would be wrong
    if version != SUPPORTED_VERSION:
        print(f"Rejected packet: unsupported version {version}")
        continue

    # side can only take 0 for bid and 1 for ask 
    if side not in (0, 1):
        print(f"Rejected packet: invalid side {side}")
        continue

    # converting values for display
    side_name = "BID" if side == 0 else "ASK"
    price = price_ticks / 100

    # print decoded packet for verification purposes - always good to include 
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
