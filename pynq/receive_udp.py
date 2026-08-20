import socket # python networking lib

LISTEN_IP = "0.0.0.0" # accept packets sento to any of the pynq's local IPV4 addresses
LISTEN_PORT = 5001 # local udp port to which packets are received. pls note that 
# send port should be same

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM) # IPV4 + UDP AF_INET6 for IPV6 
sock.bind((LISTEN_IP, LISTEN_PORT)) #udp packets sent to pynq on port 5001 can reach socket

print(f"Listening on UDP port {LISTEN_PORT}...") # not necessary just terminal output

while True: # keep waiting for UDP packets
    data, sender = sock.recvfrom(2048) 
    #data: recv payload as bytes
    # sender: sender's ip addres & source port
    # 2048: 2048 bytes

    print(f"Received {len(data)} bytes from {sender}") # disp data size -> 10 bits + sender address: unneccesary nice to have
    print("Payload:", data.decode(errors="replace")) # convert bytes into printable string -> necessary to check if were actually 
    # seeing whats bein transmitted
