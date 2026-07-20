import argparse
import socket
import struct
import sys
import time


DESTINATION_IP = "192.168.2.99"
DESTINATION_PORT = 5001

DEFAULT_PPS = 7_500
DEFAULT_DURATION = 10.0
MAX_PPS = 100_000
MAX_PLANNED_PACKETS = 10_000_000

MESSAGE_QUOTE_UPDATE = 1
MESSAGE_STREAM_START = 4
MESSAGE_STREAM_END = 5

PACKET_STRUCT = struct.Struct("!4sBBBBIQIII")
PACKET_SIZE = PACKET_STRUCT.size

MAGIC = b"HFT1"
VERSION = 1

NANOSECONDS_PER_SECOND = 1_000_000_000
SPIN_WINDOW_NS = 250_000
SEND_BUFFER_BYTES = 4 * 1024 * 1024
CONTROL_SETTLE_SECONDS = 0.050
END_MARKER_REPEATS = 5
END_MARKER_INTERVAL_SECONDS = 0.010


def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Send a paced HFT1 market-data stream over UDP."
    )
    parser.add_argument("--ip", default=DESTINATION_IP)
    parser.add_argument("--port", type=int, default=DESTINATION_PORT)
    parser.add_argument("--pps", type=int, default=DEFAULT_PPS)
    parser.add_argument("--duration", type=float, default=DEFAULT_DURATION)
    return parser.parse_args()


def wait_until(deadline_ns):
    """Sleep for the coarse interval, spin near the deadline, and return time."""
    while True:
        now_ns = time.perf_counter_ns()
        remaining_ns = deadline_ns - now_ns

        if remaining_ns <= 0:
            return now_ns

        if remaining_ns > SPIN_WINDOW_NS:
            time.sleep(
                (remaining_ns - SPIN_WINDOW_NS)
                / NANOSECONDS_PER_SECOND
            )


def pack_packet_into(
    packet_buffer,
    message_type,
    side,
    sequence,
    timestamp_ns,
    instrument_id,
    price_ticks,
    quantity,
):
    PACKET_STRUCT.pack_into(
        packet_buffer,
        0,
        MAGIC,
        VERSION,
        message_type,
        side,
        0,
        sequence,
        timestamp_ns,
        instrument_id,
        price_ticks,
        quantity,
    )


def main():
    args = parse_arguments()

    if not 1 <= args.pps <= MAX_PPS:
        print(
            f"Error: --pps must be between 1 and {MAX_PPS:,}",
            file=sys.stderr,
        )
        return 2

    if args.duration <= 0:
        print("Error: --duration must be greater than zero", file=sys.stderr)
        return 2

    if not 1 <= args.port <= 65_535:
        print("Error: --port must be between 1 and 65535", file=sys.stderr)
        return 2

    planned_packets = int(round(args.pps * args.duration))
    duration_ms = int(round(args.duration * 1_000))

    if not 1 <= planned_packets <= MAX_PLANNED_PACKETS:
        print(
            f"Error: planned packet count must be between 1 and "
            f"{MAX_PLANNED_PACKETS:,}",
            file=sys.stderr,
        )
        return 2

    if duration_ms > 0xFFFFFFFF:
        print("Error: duration exceeds the protocol field", file=sys.stderr)
        return 2

    destination = (args.ip, args.port)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, SEND_BUFFER_BYTES)
    sock.connect(destination)

    actual_send_buffer = sock.getsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF)
    packet_buffer = bytearray(PACKET_SIZE)

    print("Optimized market stream sender started")
    print(f"Destination:       {args.ip}:{args.port}")
    print(f"Packet size:       {PACKET_SIZE} bytes")
    print(f"UDP send buffer:   {actual_send_buffer:,} bytes")
    print(f"Target rate:       {args.pps:,} packets/s")
    print(f"Test duration:     {args.duration:.3f} seconds")
    print(f"Planned packets:   {planned_packets:,}")

    pack_packet_into(
        packet_buffer,
        MESSAGE_STREAM_START,
        0,
        0,
        time.time_ns(),
        args.pps,
        duration_ms,
        planned_packets,
    )
    sock.send(packet_buffer)

    # Let the receiver allocate and initialise its sequence bitmap before data.
    time.sleep(CONTROL_SETTLE_SECONDS)

    period_ns = NANOSECONDS_PER_SECOND / args.pps
    sent_packets = 0
    interrupted = False
    missed_deadlines = 0
    maximum_lateness_ns = 0
    total_lateness_ns = 0
    start_time_ns = time.perf_counter_ns()

    try:
        for sequence in range(1, planned_packets + 1):
            deadline_ns = (
                start_time_ns
                + ((sequence - 1) * NANOSECONDS_PER_SECOND) // args.pps
            )
            ready_time_ns = wait_until(deadline_ns)
            lateness_ns = ready_time_ns - deadline_ns

            total_lateness_ns += lateness_ns
            if lateness_ns > maximum_lateness_ns:
                maximum_lateness_ns = lateness_ns
            if lateness_ns >= period_ns:
                missed_deadlines += 1

            side = sequence & 1
            instrument_id = 1 + ((sequence - 1) % 3)
            price_ticks = 18_500 + (sequence % 101)
            quantity = 1 + ((sequence * 10) % 1_000)

            pack_packet_into(
                packet_buffer,
                MESSAGE_QUOTE_UPDATE,
                side,
                sequence,
                time.time_ns(),
                instrument_id,
                price_ticks,
                quantity,
            )

            bytes_sent = sock.send(packet_buffer)
            if bytes_sent != PACKET_SIZE:
                raise RuntimeError(
                    f"send() accepted {bytes_sent} of {PACKET_SIZE} bytes"
                )

            sent_packets = sequence

    except KeyboardInterrupt:
        interrupted = True
        print("\nSender interrupted")

    end_time_ns = time.perf_counter_ns()

    pack_packet_into(
        packet_buffer,
        MESSAGE_STREAM_END,
        0,
        sent_packets,
        time.time_ns(),
        args.pps,
        duration_ms,
        sent_packets,
    )

    for _ in range(END_MARKER_REPEATS):
        sock.send(packet_buffer)
        time.sleep(END_MARKER_INTERVAL_SECONDS)

    sock.close()

    elapsed_seconds = (end_time_ns - start_time_ns) / NANOSECONDS_PER_SECOND
    average_send_rate = (
        sent_packets / elapsed_seconds if elapsed_seconds > 0 else 0.0
    )
    average_lateness_ns = (
        total_lateness_ns / sent_packets if sent_packets else 0.0
    )

    print("\nStream transmission complete")
    print(f"Packets sent:           {sent_packets:,}")
    print(f"Measured duration:      {elapsed_seconds:.6f} s")
    print(f"Average send rate:      {average_send_rate:,.0f} pps")
    print(f"Missed pacing periods:  {missed_deadlines:,}")
    print(f"Average deadline error: {average_lateness_ns:,.0f} ns")
    print(f"Maximum deadline error: {maximum_lateness_ns:,} ns")

    return 130 if interrupted else 0


if __name__ == "__main__":
    raise SystemExit(main())
