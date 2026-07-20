import argparse
import resource
import socket
import struct
import time


LISTEN_IP = "0.0.0.0"
LISTEN_PORT = 5001

MESSAGE_QUOTE_UPDATE = 1
MESSAGE_STREAM_START = 4
MESSAGE_STREAM_END = 5

PACKET_STRUCT = struct.Struct("!4sBBBBIQIII")
PACKET_SIZE = PACKET_STRUCT.size

EXPECTED_MAGIC = b"HFT1"
SUPPORTED_VERSION = 1

MAX_DATAGRAM_SIZE = 2_048
RECEIVE_BUFFER_BYTES = 4 * 1024 * 1024
MAX_PLANNED_PACKETS = 10_000_000
REPORT_CHECK_PACKETS = 256
MIN_RATE_FRACTION = 0.995


def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Receive and benchmark an HFT1 UDP market-data stream."
    )
    parser.add_argument("--ip", default=LISTEN_IP)
    parser.add_argument("--port", type=int, default=LISTEN_PORT)
    return parser.parse_args()


def read_udp_statistics():
    """Return Linux UDP counters, or an empty dictionary if unavailable."""
    try:
        with open("/proc/net/snmp", "r", encoding="ascii") as snmp_file:
            rows = [line.split() for line in snmp_file]
    except OSError:
        return {}

    for index in range(len(rows) - 1):
        header = rows[index]
        values = rows[index + 1]

        if header and values and header[0] == "Udp:" and values[0] == "Udp:":
            try:
                return {
                    name: int(value)
                    for name, value in zip(header[1:], values[1:])
                }
            except ValueError:
                return {}

    return {}


def counter_delta(end_statistics, start_statistics, counter):
    return end_statistics.get(counter, 0) - start_statistics.get(counter, 0)


def print_summary(
    target_pps,
    planned_packets,
    actual_sent,
    valid_packets,
    invalid_packets,
    duplicate_packets,
    out_of_order_packets,
    highest_sequence,
    first_packet_time,
    end_time,
    udp_start,
    udp_end,
    cpu_start,
    cpu_end,
):
    missing_packets = max(0, actual_sent - valid_packets)

    if first_packet_time is None:
        measured_duration = 0.0
        average_receive_pps = 0.0
    else:
        measured_duration = end_time - first_packet_time
        average_receive_pps = (
            valid_packets / measured_duration if measured_duration > 0 else 0.0
        )

    if actual_sent > 0:
        packet_error_rate = 100.0 * missing_packets / actual_sent
        invalid_packet_rate = 100.0 * invalid_packets / actual_sent
        duplicate_packet_rate = 100.0 * duplicate_packets / actual_sent
        out_of_order_rate = 100.0 * out_of_order_packets / actual_sent
    else:
        packet_error_rate = 0.0
        invalid_packet_rate = 0.0
        duplicate_packet_rate = 0.0
        out_of_order_rate = 0.0

    rate_ok = average_receive_pps >= target_pps * MIN_RATE_FRACTION
    integrity_ok = (
        actual_sent == planned_packets
        and missing_packets == 0
        and invalid_packets == 0
        and duplicate_packets == 0
        and out_of_order_packets == 0
    )

    user_cpu = cpu_end.ru_utime - cpu_start.ru_utime
    system_cpu = cpu_end.ru_stime - cpu_start.ru_stime
    process_cpu = user_cpu + system_cpu
    process_cpu_percent = (
        100.0 * process_cpu / measured_duration
        if measured_duration > 0
        else 0.0
    )

    print("\nStream test complete")
    print(f"Target rate:             {target_pps:,} packets/s")
    print(f"Packets sent:            {actual_sent:,}")
    print(f"Valid unique packets:    {valid_packets:,}")
    print(f"Missing packets:         {missing_packets:,}")
    print(f"Invalid packets:         {invalid_packets:,}")
    print(f"Duplicate packets:       {duplicate_packets:,}")
    print(f"Out-of-order packets:    {out_of_order_packets:,}")
    print(f"Highest sequence:        {highest_sequence:,}")
    print(f"Measured duration:       {measured_duration:.6f} s")
    print(f"Average receive rate:    {average_receive_pps:,.0f} pps")
    print(f"Packet error rate:       {packet_error_rate:.6f}%")
    print(f"Invalid packet rate:     {invalid_packet_rate:.6f}%")
    print(f"Duplicate packet rate:   {duplicate_packet_rate:.6f}%")
    print(f"Out-of-order rate:       {out_of_order_rate:.6f}%")
    print(f"Process user CPU:        {user_cpu:.3f} s")
    print(f"Process system CPU:      {system_cpu:.3f} s")
    print(f"Process CPU utilisation: {process_cpu_percent:.1f}% of one core")

    if udp_start and udp_end:
        print(
            f"Kernel UDP InErrors:     "
            f"{counter_delta(udp_end, udp_start, 'InErrors'):,}"
        )
        print(
            f"Kernel UDP RcvbufErrors: "
            f"{counter_delta(udp_end, udp_start, 'RcvbufErrors'):,}"
        )

    print(f"Real-time rate check:    {'PASS' if rate_ok else 'FAIL'}")
    print(f"Result:                  {'PASS' if integrity_ok and rate_ok else 'FAIL'}")


def main():
    args = parse_arguments()

    if not 1 <= args.port <= 65_535:
        raise SystemExit("--port must be between 1 and 65535")

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(
        socket.SOL_SOCKET,
        socket.SO_RCVBUF,
        RECEIVE_BUFFER_BYTES,
    )
    sock.bind((args.ip, args.port))

    actual_buffer = sock.getsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF)
    receive_buffer = bytearray(MAX_DATAGRAM_SIZE)

    stream_active = False
    active_sender = None
    target_pps = 0
    planned_packets = 0
    seen_sequences = None

    valid_packets = 0
    invalid_packets = 0
    duplicate_packets = 0
    out_of_order_packets = 0
    highest_sequence = 0

    first_packet_time = None
    last_report_time = None
    packets_at_last_report = 0
    next_report_check = REPORT_CHECK_PACKETS

    udp_start = {}
    cpu_start = None

    print(f"Listening for {PACKET_SIZE}-byte market packets...")
    print(f"UDP port:           {args.port}")
    print(f"UDP receive buffer: {actual_buffer:,} bytes")

    try:
        while True:
            received_bytes, sender = sock.recvfrom_into(receive_buffer)

            if received_bytes != PACKET_SIZE:
                if stream_active:
                    invalid_packets += 1
                continue

            (
                magic,
                version,
                message_type,
                side,
                flags,
                sequence,
                _timestamp_ns,
                instrument_id,
                price_ticks,
                quantity,
            ) = PACKET_STRUCT.unpack_from(receive_buffer)

            if magic != EXPECTED_MAGIC or version != SUPPORTED_VERSION:
                if stream_active:
                    invalid_packets += 1
                continue

            if message_type == MESSAGE_STREAM_START:
                new_target_pps = instrument_id
                duration_ms = price_ticks
                new_planned_packets = quantity

                if (
                    new_target_pps < 1
                    or duration_ms < 1
                    or new_planned_packets < 1
                    or new_planned_packets > MAX_PLANNED_PACKETS
                ):
                    continue

                stream_active = True
                active_sender = sender
                target_pps = new_target_pps
                planned_packets = new_planned_packets
                seen_sequences = bytearray(planned_packets + 1)

                valid_packets = 0
                invalid_packets = 0
                duplicate_packets = 0
                out_of_order_packets = 0
                highest_sequence = 0

                first_packet_time = None
                last_report_time = None
                packets_at_last_report = 0
                next_report_check = REPORT_CHECK_PACKETS

                udp_start = read_udp_statistics()
                cpu_start = resource.getrusage(resource.RUSAGE_SELF)

                print("\nStream test started")
                print(f"Sender:          {sender}")
                print(f"Target rate:     {target_pps:,} packets/s")
                print(f"Test duration:   {duration_ms / 1000:.3f} seconds")
                print(f"Planned packets: {planned_packets:,}")
                continue

            if message_type == MESSAGE_STREAM_END:
                if not stream_active or sender != active_sender:
                    continue

                actual_sent = quantity
                if not 1 <= actual_sent <= planned_packets:
                    actual_sent = sequence
                if not 1 <= actual_sent <= planned_packets:
                    actual_sent = planned_packets

                end_time = time.perf_counter()
                udp_end = read_udp_statistics()
                cpu_end = resource.getrusage(resource.RUSAGE_SELF)

                print_summary(
                    target_pps,
                    planned_packets,
                    actual_sent,
                    valid_packets,
                    invalid_packets,
                    duplicate_packets,
                    out_of_order_packets,
                    highest_sequence,
                    first_packet_time,
                    end_time,
                    udp_start,
                    udp_end,
                    cpu_start,
                    cpu_end,
                )

                stream_active = False
                active_sender = None
                seen_sequences = None
                continue

            if not stream_active:
                continue

            if sender != active_sender:
                invalid_packets += 1
                continue

            if (
                message_type != MESSAGE_QUOTE_UPDATE
                or side not in (0, 1)
                or flags != 0
                or not 1 <= sequence <= planned_packets
            ):
                invalid_packets += 1
                continue

            if seen_sequences[sequence]:
                duplicate_packets += 1
                continue

            seen_sequences[sequence] = 1
            valid_packets += 1

            if sequence < highest_sequence:
                out_of_order_packets += 1
            elif sequence > highest_sequence:
                highest_sequence = sequence

            if first_packet_time is None:
                first_packet_time = time.perf_counter()
                last_report_time = first_packet_time

            if valid_packets >= next_report_check:
                now = time.perf_counter()

                if now - last_report_time >= 1.0:
                    report_elapsed = now - last_report_time
                    interval_packets = valid_packets - packets_at_last_report
                    interval_rate = interval_packets / report_elapsed

                    print(
                        f"Valid: {valid_packets:,} | "
                        f"Invalid: {invalid_packets:,} | "
                        f"Duplicates: {duplicate_packets:,} | "
                        f"Out of order: {out_of_order_packets:,} | "
                        f"Rate: {interval_rate:,.0f} pps"
                    )

                    last_report_time = now
                    packets_at_last_report = valid_packets

                next_report_check = valid_packets + REPORT_CHECK_PACKETS

    except KeyboardInterrupt:
        print("\nReceiver stopped")

    finally:
        sock.close()


if __name__ == "__main__":
    main()
