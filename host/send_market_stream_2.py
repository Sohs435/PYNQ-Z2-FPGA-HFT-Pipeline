
"""Generate and transmit a paced stream of 32-byte market-data packets."""
import argparse
import socket
import struct
import sys
import time


DESTINATION_IP = "192.168.2.99"
DESTINATION_PORT = 5001

MAX_PPS = 7_500
DEFAULT_PPS = 7_500
DEFAULT_DURATION = 10.0

MAGIC = b"HFT1"
VERSION = 1

MESSAGE_QUOTE = 1
CONTROL_START = 254
CONTROL_END = 255

PACKET_STRUCT = struct.Struct("!4sBBBBIQIII")
PACKET_SIZE = PACKET_STRUCT.size

NANOSECONDS_PER_SECOND = 1_000_000_000
SPIN_WINDOW_NS = 250_000
SEND_BUFFER_BYTES = 4 * 1024 * 1024


def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Send a paced stream of synthetic HFT1 market packets."
    )
    parser.add_argument(
        "--ip",
        default=DESTINATION_IP,
        help=f"destination IPv4 address (default: {DESTINATION_IP})",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DESTINATION_PORT,
        help=f"destination UDP port (default: {DESTINATION_PORT})",
    )
    parser.add_argument(
        "--pps",
        type=int,
        default=DEFAULT_PPS,
        help=f"packets per second, maximum {MAX_PPS} (default: {DEFAULT_PPS})",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=DEFAULT_DURATION,
        help=f"test duration in seconds (default: {DEFAULT_DURATION})",
    )
    return parser.parse_args()


def wait_until(deadline_ns):
    """Sleep when possible, then spin briefly for accurate packet pacing."""

    while True:
        now_ns = time.perf_counter_ns()
        remaining_ns = deadline_ns - now_ns

        if remaining_ns <= 0:
            return

        if remaining_ns > SPIN_WINDOW_NS:
            time.sleep((remaining_ns - SPIN_WINDOW_NS) / NANOSECONDS_PER_SECOND)


#builds and returns a 32 byte packet given certain inputs (can be anything honestly
#like target_pps does not have anything to do with the actual HFT packet format but
#some of the fields have been converted to use those values since they can be any number)
#pay them no heed
def make_control_packet(message_type, sequence, target_pps, duration_ms, count):
    return PACKET_STRUCT.pack(
        MAGIC,
        VERSION,
        message_type,
        0,
        0,
        sequence,
        time.time_ns(),
        target_pps,
        duration_ms,
        count,
    )


#create one synthetic market-data quote purely based on sequence 
def make_quote_packet(sequence):
    side = sequence & 1
    instrument_id = 1 + ((sequence - 1) % 3)
    price_ticks = 18_500 + (sequence % 101)
    quantity = 1 + ((sequence * 10) % 1_000)

    return PACKET_STRUCT.pack(
        MAGIC,
        VERSION,
        MESSAGE_QUOTE,
        side,
        0,
        sequence,
        time.time_ns(),
        instrument_id,
        price_ticks,
        quantity,
    )

#ensure that pps, ip, duration, port are all actually capturable/usable values
#you cant have a pps or duration lt0 or a port not within the possible range of ports
def validate_arguments(args, planned_packets, duration_ms):
    if args.pps <= 0:
        raise ValueError("--pps must be greater than zero")

    if args.pps > MAX_PPS:
        raise ValueError(
            f"--pps cannot exceed the validated cap of {MAX_PPS:,} packets/s"
        )

    if args.duration <= 0:
        raise ValueError("--duration must be greater than zero")

    if not 1 <= args.port <= 65_535:
        raise ValueError("--port must be between 1 and 65535")

    if planned_packets <= 0:
        raise ValueError("the selected rate and duration produce no packets")

    if planned_packets > 0xFFFFFFFF:
        raise ValueError("planned packet count exceeds the 32-bit control field")

    if duration_ms > 0xFFFFFFFF:
        raise ValueError("duration exceeds the 32-bit control field")


def main():
    args = parse_arguments() #ip, port, duration, sender rate 
    planned_packets = int(round(args.pps * args.duration)) #7500pps * 10s = 75000 total packets
    duration_ms = int(round(args.duration * 1_000)) #convert 10s to 10000ms 

    try:
        validate_arguments(args, planned_packets, duration_ms)
    except ValueError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2

    destination = (args.ip, args.port)# destination contains IP = 192.168.2.99 and port 5001b 
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM) #create IPV4 UDP socket 
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, SEND_BUFFER_BYTES)# create larger outgoing
    #send buffer
    #send buffer bytes = 4 * 1024 * 1024 = 4MiB
    #tbh this is a bit much since we cannot expect so many packets to build up on the sender's stack
    #its set very high to be needlessly safe (ex for a 100ms stall 750 packet que is the minimum)  

    #let user know sender has started to transmit data to the given ip and port with given packet size
    #etc... 
    print("Market stream sender started")
    print(f"Destination:     {args.ip}:{args.port}")
    print(f"Packet size:     {PACKET_SIZE} bytes")
    print(f"Target rate:     {args.pps:,} packets/s")
    print(f"Test duration:   {args.duration:.3f} seconds")
    print(f"Planned packets: {planned_packets:,}")

    #create control (start) packet to send over UDP before the quote packets 
    start_control = make_control_packet(
        CONTROL_START,
        0,
        args.pps,
        duration_ms,
        planned_packets,
    )
    sock.sendto(start_control, destination)

    # Give the receiver a brief opportunity to initialise its sequence bitmap.
    time.sleep(0.05)

    sent_packets = 0
    interrupted = False
    start_ns = time.perf_counter_ns()

    try:
        for sequence in range(1, planned_packets + 1):
            deadline_ns = (
                start_ns
                + ((sequence - 1) * NANOSECONDS_PER_SECOND) // args.pps
            ) #consider a 1/7500 second window in which the packet needs to be sent 
            #t_diff = (start_ns - (k) * 10^9/7500) - (start_ns - (k-1) * 10^9/7500) = (10^9/7500)ns 
            wait_until(deadline_ns)

            #create quote packet 
            packet = make_quote_packet(sequence)
            bytes_sent = sock.sendto(packet, destination)

            #32 byte packet needs to be sent 
            if bytes_sent != PACKET_SIZE:
                raise RuntimeError(
                    f"sendto() accepted {bytes_sent} of {PACKET_SIZE} bytes"
                )

            sent_packets = sequence

    except KeyboardInterrupt:
        interrupted = True
        print("\nSender interrupted")

    #create ending packet 
    finally:
        end_ns = time.perf_counter_ns()
        end_control = make_control_packet(
            CONTROL_END,
            sent_packets,
            args.pps,
            duration_ms,
            sent_packets,
        )

        # Send end/final packet 5 times every 10ms to make it more likely the receiver at least gets 
        # 1 packet because udp has no triple handshake like tcp
        for _ in range(5):
            sock.sendto(end_control, destination)
            time.sleep(0.01)

        sock.close()

    #overall time between start of packet stream and end of packet stream in seconds 
    #should be extremely close to duration 
    elapsed_seconds = (end_ns - start_ns) / NANOSECONDS_PER_SECOND
    average_rate = sent_packets / elapsed_seconds if elapsed_seconds > 0 else 0.0
    #should be extremely close to pps (wont be 100 perfect though)

    print("\nStream transmission complete")
    print(f"Packets sent:     {sent_packets:,}")
    print(f"Measured duration: {elapsed_seconds:.3f} s")
    print(f"Average send rate: {average_rate:,.0f} pps")

    #130 since signal interrupt handled by code like ctrl + C
    return 130 if interrupted else 0


if __name__ == "__main__":
    raise SystemExit(main())
