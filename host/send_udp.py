import socket

PYNQ_IP = "192.168.2.99"
PYNQ_PORT = 5001

message = "Hello FPGA"
payload = message.encode()

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

try:
    bytes_sent = sock.sendto(
        payload,
        (PYNQ_IP, PYNQ_PORT),
    )

    print(f"Sent {bytes_sent} bytes to {PYNQ_IP}:{PYNQ_PORT}")

finally:
    sock.close()
