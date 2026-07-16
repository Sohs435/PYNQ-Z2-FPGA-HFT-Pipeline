import socket

LISTEN_IP = "0.0.0.0"
LISTEN_PORT = 5001

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind((LISTEN_IP, LISTEN_PORT))

print(f"Listening on UDP port {LISTEN_PORT}...")

while True:
    data, sender = sock.recvfrom(2048)

    print(f"Received {len(data)} bytes from {sender}")
    print("Payload:", data.decode(errors="replace"))
