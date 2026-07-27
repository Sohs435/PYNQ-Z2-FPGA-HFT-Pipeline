#!/usr/bin/env python3
"""Laptop sender for the Phase 4.9 live FPGA integration test."""

import argparse
import socket
import struct
import time


DEFAULT_DESTINATION_IP = "192.168.2.99"
DEFAULT_DESTINATION_PORT = 5001
DEFAULT_PPS = 1_000
DEFAULT_DURATION = 2.0

MESSAGE_QUOTE_UPDATE = 1
MESSAGE_STREAM_START = 4
MESSAGE_STREAM_END = 5

PACKET_STRUCT = struct.Struct("!4sBBBBIQIII")


def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Send a deterministic live HFT1 UDP stream to PYNQ."
    )
    parser.add_argument(
        "--ip",
        default=DEFAULT_DESTINATION_IP,
        help=f"PYNQ IPv4 address (default: {DEFAULT_DESTINATION_IP})",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_DESTINATION_PORT,
        help=f"PYNQ UDP port (default: {DEFAULT_DESTINATION_PORT})",
    )
    parser.add_argument(
        "--pps",
        type=int,
        default=DEFAULT_PPS,
        help=f"target packet rate (default: {DEFAULT_PPS})",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=DEFAULT_DURATION,
        help=f"test duration in seconds (default: {DEFAULT_DURATION})",
    )
    return parser.parse_args()


def build_packet(packet_index, total_packets, target_pps, duration_ms):
    """Build STREAM_START, quote updates, and STREAM_END packets."""

    sequence = packet_index + 1
    timestamp_ns = time.time_ns()

    if packet_index == 0:
        message_type = MESSAGE_STREAM_START
        side = 0
        instrument_id = target_pps
        price_ticks = duration_ms
        quantity = total_packets
    elif packet_index == total_packets - 1:
        message_type = MESSAGE_STREAM_END
        side = 0
        instrument_id = 0
        price_ticks = 0
        quantity = 0
    else:
        message_type = MESSAGE_QUOTE_UPDATE
        side = sequence & 1
        instrument_id = 1 + (packet_index % 4)
        price_ticks = 100_000 + (packet_index % 1_000)
        quantity = 1 + (packet_index % 100)

    return PACKET_STRUCT.pack(
        b"HFT1",
        1,
        message_type,
        side,
        0,
        sequence,
        timestamp_ns,
        instrument_id,
        price_ticks,
        quantity,
    )


def wait_until(deadline_ns):
    """Sleep for the coarse delay, then spin for the final short interval."""

    while True:
        remaining_ns = deadline_ns - time.perf_counter_ns()

        if remaining_ns <= 0:
            return

        if remaining_ns > 500_000:
            time.sleep((remaining_ns - 200_000) / 1_000_000_000)


def main():
    args = parse_arguments()

    if args.pps <= 0:
        raise ValueError("--pps must be positive")

    if args.duration <= 0:
        raise ValueError("--duration must be positive")

    total_packets = max(2, round(args.pps * args.duration))
    duration_ms = round(args.duration * 1_000)
    packet_interval_ns = 1_000_000_000 // args.pps

    print("Phase 4.9 - live HFT1 UDP sender")
    print(f"Destination:       {args.ip}:{args.port}")
    print(f"Target rate:       {args.pps:,} packets/s")
    print(f"Duration:          {args.duration:.3f} s")
    print(f"Planned packets:   {total_packets:,}")
    print(f"Packet size:       {PACKET_STRUCT.size} bytes")

    udp_socket = socket.socket(
        socket.AF_INET,
        socket.SOCK_DGRAM,
    )
    udp_socket.setsockopt(
        socket.SOL_SOCKET,
        socket.SO_SNDBUF,
        4 * 1024 * 1024,
    )

    first_send_ns = None
    final_send_ns = None

    try:
        schedule_start_ns = time.perf_counter_ns() + 100_000_000

        for packet_index in range(total_packets):
            deadline_ns = (
                schedule_start_ns
                + packet_index * packet_interval_ns
            )
            wait_until(deadline_ns)

            packet = build_packet(
                packet_index,
                total_packets,
                args.pps,
                duration_ms,
            )
            udp_socket.sendto(
                packet,
                (args.ip, args.port),
            )

            send_ns = time.perf_counter_ns()

            if first_send_ns is None:
                first_send_ns = send_ns

            final_send_ns = send_ns

    finally:
        udp_socket.close()

    if (
        first_send_ns is not None
        and final_send_ns is not None
        and final_send_ns > first_send_ns
    ):
        elapsed_s = (
            final_send_ns - first_send_ns
        ) / 1_000_000_000
        achieved_pps = (total_packets - 1) / elapsed_s
    else:
        elapsed_s = 0.0
        achieved_pps = 0.0

    print("\nSender complete")
    print(f"Packets sent:      {total_packets:,}")
    print(f"Elapsed time:      {elapsed_s:.6f} s")
    print(f"Achieved rate:     {achieved_pps:,.1f} packets/s")


if __name__ == "__main__":
    main()
