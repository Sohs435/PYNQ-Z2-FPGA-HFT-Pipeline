import socket
import struct
import time

PYNQ_IP = "192.168.2.99"
PYNQ_PORT = 5001

PACKET_FORMAT = "!4sBBBBIQIII"
PACKET_SIZE = struct.calcsize(PACKET_FORMAT)

MAGIC = b"HFT1"
VERSION = 1
MESSAGE_TYPE = 1       # Quote update
SIDE = 0               # 0 = bid, 1 = ask
FLAGS = 0

SEQUENCE = 1
INSTRUMENT_ID = 1      # 1 = AAPL
PRICE_TICKS = 18_525   # $185.25
QUANTITY = 100

timestamp_ns = time.time_ns()

packet = struct.pack(
    PACKET_FORMAT,
    MAGIC,
    VERSION,
    MESSAGE_TYPE,
    SIDE,
    FLAGS,
    SEQUENCE,
    timestamp_ns,
    INSTRUMENT_ID,
    PRICE_TICKS,
    QUANTITY,
)

if len(packet) != PACKET_SIZE:
    raise RuntimeError("Incorrect packet size")

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

try:
    bytes_sent = sock.sendto(packet, (PYNQ_IP, PYNQ_PORT))

    print(f"Sent {bytes_sent} bytes to {PYNQ_IP}:{PYNQ_PORT}")
    print("Packet:", packet.hex(" "))

finally:
    sock.close()
