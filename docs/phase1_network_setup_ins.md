# Network Setup - Phase 1

## Hardware Connection

Laptop Ethernet port to PYNQ-Z2 RJ45 Ethernet port

The laptop uses Wi-Fi for Internet access while the Ethernet interface is used
exclusively for communication with the PYNQ-Z2.

---

## Network Configuration

### Windows

- IPv4 Address: `192.168.2.1`
- Subnet Mask: `255.255.255.0`
- Default Gateway: leave blank
- DNS Server: leave blank

### PYNQ-Z2

- IPv4 Address: `192.168.2.99`
- Prefix: `/24`
- Interface: `eth0`

---

## Verification

### 1. Verify Ethernet interface

```bash
ip addr show eth0
```

Output:

```text
inet 192.168.2.99/24
```

---

### 2. Verify the physical Ethernet link

```bash
cat /sys/class/net/eth0/carrier
```

Expected output:

```text
1
```

A value of `1` indicates that the Ethernet cable is connected and the physical link is active.

---

### 3. Verify the negotiated link speed

```bash
cat /sys/class/net/eth0/speed
```

Expected output:

```text
1000
```

This confirms a 1 Gbps Ethernet connection.

---

### 4. Verify duplex mode

```bash
cat /sys/class/net/eth0/duplex
```

Expected output:

```text
full
```

This confirms the interface is operating in full-duplex mode.

---

### 5. Verify network connectivity (Windows)

Open PowerShell or Command Prompt and run:

```powershell
ping 192.168.2.99
```

Expected output of the form:

```text
Pinging 192.168.2.99 with 32 bytes of data:
Reply from 192.168.2.99: bytes=32 time=1ms TTL=64
Reply from 192.168.2.99: bytes=32 time=1ms TTL=64
Reply from 192.168.2.99: bytes=32 time=1ms TTL=64
Reply from 192.168.2.99: bytes=32 time=1ms TTL=64

Packets: Sent = 4, Received = 4, Lost = 0 (0% loss)
```

---

## Step by step start up instructions

1. Insert SD-card into PYNQ Z2 board
2. Connect the Ethernet cable between the computer and the PYNQ-Z2.
3. Configure the Windows Ethernet adapter with the static IPv4 address `192.168.2.1/24`.
4. Power on the PYNQ-Z2.
5. Verify the PYNQ IP address using `ip addr show eth0`.
6. Verify the Ethernet link using `cat /sys/class/net/eth0/carrier`.
7. Ping `192.168.2.99` from the Windows host.

Move on to Phase 2 if all steps completed and verification goes smoothly
