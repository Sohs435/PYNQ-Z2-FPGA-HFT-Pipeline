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
