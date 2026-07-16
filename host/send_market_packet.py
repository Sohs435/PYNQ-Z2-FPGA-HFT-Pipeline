import socket #send data thru network
import struct #convert int + str into fixed binary bytes
import time # timestamping

# Destination IP + port - tells computer where to send packet to i.e The PYNQ Z2 board
PYNQ_IP = "192.168.2.99" 
PYNQ_PORT = 5001

# Big endian byte order + protocol ID + ... + quantity pls ref to phase 2 in docs for more complete understanding - this is an example in valid format
# Describes order + width of every field
PACKET_FORMAT = "!4sBBBBIQIII"
PACKET_SIZE = struct.calcsize(PACKET_FORMAT)

#Market Data values 
MAGIC = b"HFT1" # Protocol ID
VERSION = 1
MESSAGE_TYPE = 1       # Quote update
SIDE = 0               # 0 = bid, 1 = ask
FLAGS = 0
SEQUENCE = 1
INSTRUMENT_ID = 1      # 1 = AAPL 
PRICE_TICKS = 18_525   # $185.25
QUANTITY = 100

# Obtains computer's current timestamp as an integer in ns
timestamp_ns = time.time_ns()

#packing the packet - packet is now just 1 32 byte obj
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

# saftety check - program stops if packet is not right size rather than transmitting a bad packet
if len(packet) != PACKET_SIZE:
    raise RuntimeError("Incorrect packet size")

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM) # create UDP socket that uses IPV4

# send packet to the correct IP plus port
try:
    bytes_sent = sock.sendto(packet, (PYNQ_IP, PYNQ_PORT))

    # just printing the bytes
    print(f"Sent {bytes_sent} bytes to {PYNQ_IP}:{PYNQ_PORT}")
    print("Packet:", packet.hex(" "))

# close socket once packet is sent and free up networking resource
finally:
    sock.close()
