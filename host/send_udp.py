import socket  # Import Python's networking library

# IP address and UDP port of the PYNQ board
PYNQ_IP = "192.168.2.99"
PYNQ_PORT = 5001

# Message that will be sent to the PYNQ board
message = "Hello FPGA"

# Convert the Python string into bytes because sockets transmit bytes
# "Hello FPGA" contains 10 bytes
payload = message.encode()

# Create an IPv4 UDP socket
# AF_INET means use IPv4 addresses
# SOCK_DGRAM means use the UDP protocol
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

try:
    # Send one UDP packet containing payload to the specified IP and port
    # sendto() returns the number of payload bytes accepted for transmission
    bytes_sent = sock.sendto(
        payload,
        (PYNQ_IP, PYNQ_PORT),
    )

    # This confirms that the local OS accepted the bytes for transmission
    # It does not guarantee that the PYNQ board received them because UDP
    # does not provide acknowledgements
    print(f"Sent {bytes_sent} bytes to {PYNQ_IP}:{PYNQ_PORT}")

finally:
    # close socket always cuz its an OS resource and not just a variable 
    # ensures that socket closes even if sending fails 
    sock.close()
