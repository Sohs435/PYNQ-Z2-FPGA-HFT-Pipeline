#!/usr/bin/env python3
"""Live HFT1 UDP -> DDR -> DMA -> FPGA parser -> DDR test for PYNQ.

Run this program on the PYNQ first. It receives live 32-byte UDP payloads,
collects them into batches, copies each batch into physically contiguous PS DDR,
passes it through the AXI DMA and HFT1 parser, and compares the S2MM output in
PS DDR against the original UDP bytes.
"""

import argparse
import socket
import struct
import time

import numpy as np
from pynq import Overlay, allocate


DEFAULT_BITSTREAM = (
    "/home/xilinx/PYNQ_HFT/phase4_packet_parser/"
    "phase4_packet_parser_2.bit"
)
DEFAULT_PORT = 5001
DEFAULT_BATCH_PACKETS = 256
DEFAULT_TIMEOUT = 10.0
SOCKET_BUFFER_BYTES = 8 * 1024 * 1024

PACKET_STRUCT = struct.Struct("!4sBBBBIQIII")
PACKET_SIZE = PACKET_STRUCT.size

MESSAGE_QUOTE_UPDATE = 1
MESSAGE_STREAM_START = 4
MESSAGE_STREAM_END = 5
SUPPORTED_TYPES = {
    MESSAGE_QUOTE_UPDATE,
    MESSAGE_STREAM_START,
    MESSAGE_STREAM_END,
}


def parse_arguments():
    parser = argparse.ArgumentParser(
        description=(
            "Receive live HFT1 UDP packets and pass them through the FPGA "
            "packet parser using batched AXI DMA transfers."
        )
    )
    parser.add_argument(
        "--bind-ip",
        default="0.0.0.0",
        help="local IPv4 address to bind (default: all interfaces)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"UDP destination port (default: {DEFAULT_PORT})",
    )
    parser.add_argument(
        "--batch-packets",
        type=int,
        default=DEFAULT_BATCH_PACKETS,
        help=(
            "maximum packets per DMA batch "
            f"(default: {DEFAULT_BATCH_PACKETS})"
        ),
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help=(
            "seconds without a UDP packet before stopping "
            f"(default: {DEFAULT_TIMEOUT})"
        ),
    )
    parser.add_argument(
        "--bitstream",
        default=DEFAULT_BITSTREAM,
        help="path to the Phase 4 batch-mode bitstream",
    )
    parser.add_argument(
        "--no-download",
        action="store_true",
        help=(
            "do not program the FPGA; use when Vivado Hardware Manager "
            "already programmed the matching bitstream"
        ),
    )
    return parser.parse_args()


def protocol_is_valid(fields):
    """Apply the same basic HFT1 checks as the RTL parser."""

    (
        magic,
        version,
        message_type,
        side,
        reserved,
        _sequence,
        _timestamp_ns,
        _instrument_id,
        _price_ticks,
        _quantity,
    ) = fields

    if magic != b"HFT1" or version != 1 or reserved != 0:
        return False

    if message_type not in SUPPORTED_TYPES:
        return False

    if message_type == MESSAGE_QUOTE_UPDATE:
        return side in (0, 1)

    return side == 0


def compare_batch(expected, received, first_stream_index):
    """Return packet mismatch count and up to five examples."""

    mismatches = 0
    examples = []
    packet_count = len(expected) // PACKET_SIZE

    for local_index in range(packet_count):
        start = local_index * PACKET_SIZE
        stop = start + PACKET_SIZE
        expected_packet = expected[start:stop]
        received_packet = received[start:stop]

        if expected_packet != received_packet:
            mismatches += 1

            if len(examples) < 5:
                examples.append(
                    (
                        first_stream_index + local_index,
                        expected_packet.hex(),
                        received_packet.hex(),
                    )
                )

    return mismatches, examples


def transfer_batch(dma, tx_buffer, rx_buffer, packets):
    """Transfer one list of UDP payloads through the complete FPGA path."""

    expected = b"".join(packets)
    batch_bytes = len(expected)

    tx_buffer[:batch_bytes] = np.frombuffer(
        expected,
        dtype=np.uint8,
    )
    rx_buffer[:batch_bytes] = 0

    tx_buffer.flush()
    rx_buffer.flush()

    # S2MM must be ready before MM2S starts producing AXI stream data.
    dma.recvchannel.transfer(
        rx_buffer,
        nbytes=batch_bytes,
    )
    dma.sendchannel.transfer(
        tx_buffer,
        nbytes=batch_bytes,
    )

    dma.sendchannel.wait()
    dma.recvchannel.wait()

    rx_buffer.invalidate()
    received = rx_buffer[:batch_bytes].tobytes()
    return expected, received


def main():
    args = parse_arguments()

    if args.batch_packets <= 0:
        raise ValueError("--batch-packets must be positive")

    if args.timeout <= 0:
        raise ValueError("--timeout must be positive")

    max_batch_bytes = args.batch_packets * PACKET_SIZE

    print("Phase 4.9 - live UDP -> DDR -> DMA -> parser -> DDR test")
    print(f"Bind address:          {args.bind_ip}:{args.port}")
    print(f"Packet size:           {PACKET_SIZE} bytes")
    print(f"Packets per DMA batch: {args.batch_packets}")
    print(f"Maximum batch bytes:   {max_batch_bytes:,}")
    print(f"Socket timeout:        {args.timeout:.1f} s")
    print(f"Bitstream:             {args.bitstream}")
    print(f"Download overlay:      {not args.no_download}")

    print("\nLoading overlay...")
    overlay = Overlay(
        args.bitstream,
        download=not args.no_download,
    )
    print(f"Available IP: {list(overlay.ip_dict.keys())}")
    dma = overlay.axi_dma_0

    tx_buffer = allocate(
        shape=(max_batch_bytes,),
        dtype=np.uint8,
    )
    rx_buffer = allocate(
        shape=(max_batch_bytes,),
        dtype=np.uint8,
    )

    udp_socket = socket.socket(
        socket.AF_INET,
        socket.SOCK_DGRAM,
    )
    udp_socket.setsockopt(
        socket.SOL_SOCKET,
        socket.SO_RCVBUF,
        SOCKET_BUFFER_BYTES,
    )
    udp_socket.bind((args.bind_ip, args.port))
    udp_socket.settimeout(args.timeout)

    received_packets = 0
    valid_packets = 0
    invalid_packets = 0
    malformed_lengths = 0
    quote_packets = 0
    stream_start_packets = 0
    stream_end_packets = 0

    dma_batches = 0
    dma_packets = 0
    dma_errors = 0
    mismatched_packets = 0
    mismatch_examples = []

    missing_sequences = 0
    duplicate_sequences = 0
    out_of_order_sequences = 0
    seen_sequences = set()
    highest_sequence = None

    planned_packets = None
    announced_pps = None
    announced_duration_ms = None
    sender_address = None
    stream_end_seen = False
    timed_out = False

    pending_packets = []
    pending_first_index = 0
    first_receive_ns = None
    final_receive_ns = None

    def flush_pending():
        """Run the currently accumulated UDP payloads through the FPGA."""

        nonlocal dma_batches
        nonlocal dma_packets
        nonlocal dma_errors
        nonlocal mismatched_packets
        nonlocal mismatch_examples
        nonlocal pending_packets
        nonlocal pending_first_index

        if not pending_packets:
            return True

        try:
            expected, received = transfer_batch(
                dma,
                tx_buffer,
                rx_buffer,
                pending_packets,
            )
        except Exception as error:
            dma_errors += 1
            print(
                f"\nDMA error in batch {dma_batches}: {error}"
            )
            return False

        batch_mismatches, examples = compare_batch(
            expected,
            received,
            pending_first_index,
        )

        mismatched_packets += batch_mismatches
        mismatch_examples.extend(
            examples[: max(0, 10 - len(mismatch_examples))]
        )

        dma_batches += 1
        dma_packets += len(pending_packets)
        pending_packets = []
        pending_first_index = received_packets
        return True

    print("\nReceiver ready. Start the sender on the laptop now.")

    try:
        while not stream_end_seen:
            try:
                payload, address = udp_socket.recvfrom(65535)
            except socket.timeout:
                timed_out = True
                print("\nUDP receive timeout before STREAM_END")
                break

            receive_ns = time.perf_counter_ns()

            if first_receive_ns is None:
                first_receive_ns = receive_ns
                sender_address = address

            final_receive_ns = receive_ns
            received_packets += 1

            if len(payload) != PACKET_SIZE:
                malformed_lengths += 1
                invalid_packets += 1
                continue

            fields = PACKET_STRUCT.unpack(payload)
            (
                _magic,
                _version,
                message_type,
                _side,
                _reserved,
                sequence,
                _timestamp_ns,
                instrument_id,
                price_ticks,
                quantity,
            ) = fields

            if protocol_is_valid(fields):
                valid_packets += 1

                if sequence in seen_sequences:
                    duplicate_sequences += 1
                elif (
                    highest_sequence is not None
                    and sequence < highest_sequence
                ):
                    out_of_order_sequences += 1
                else:
                    if (
                        highest_sequence is not None
                        and sequence > highest_sequence + 1
                    ):
                        missing_sequences += (
                            sequence - highest_sequence - 1
                        )

                    highest_sequence = sequence

                seen_sequences.add(sequence)

                if message_type == MESSAGE_QUOTE_UPDATE:
                    quote_packets += 1
                elif message_type == MESSAGE_STREAM_START:
                    stream_start_packets += 1
                    announced_pps = instrument_id
                    announced_duration_ms = price_ticks
                    planned_packets = quantity
                elif message_type == MESSAGE_STREAM_END:
                    stream_end_packets += 1
                    stream_end_seen = True
            else:
                invalid_packets += 1

            # Every correctly-sized payload is passed through the FPGA. This
            # keeps the DMA byte comparison faithful to what arrived over UDP.
            if not pending_packets:
                pending_first_index = received_packets - 1

            pending_packets.append(payload)

            if (
                len(pending_packets) == args.batch_packets
                or stream_end_seen
            ):
                if not flush_pending():
                    break

        # Preserve and verify a partial batch if the sender stopped early.
        flush_pending()

    except KeyboardInterrupt:
        print("\nReceiver interrupted by user")
        flush_pending()

    finally:
        udp_socket.close()
        tx_buffer.freebuffer()
        rx_buffer.freebuffer()

    if (
        first_receive_ns is not None
        and final_receive_ns is not None
        and final_receive_ns > first_receive_ns
    ):
        receive_duration_s = (
            final_receive_ns - first_receive_ns
        ) / 1_000_000_000
        receive_rate_pps = (
            (received_packets - 1) / receive_duration_s
        )
    else:
        receive_duration_s = 0.0
        receive_rate_pps = 0.0

    planned_count_matches = (
        planned_packets is None
        or received_packets == planned_packets
    )

    overall_pass = (
        stream_end_seen
        and not timed_out
        and received_packets > 0
        and valid_packets == received_packets
        and malformed_lengths == 0
        and missing_sequences == 0
        and duplicate_sequences == 0
        and out_of_order_sequences == 0
        and dma_packets == received_packets
        and mismatched_packets == 0
        and dma_errors == 0
        and planned_count_matches
    )

    print("\nResults")
    print("-------")
    print(f"Sender:                 {sender_address}")
    print(f"Announced packet rate:  {announced_pps}")
    print(f"Announced duration:     {announced_duration_ms} ms")
    print(f"Announced packets:      {planned_packets}")
    print(f"UDP packets received:   {received_packets:,}")
    print(f"Protocol-valid packets: {valid_packets:,}")
    print(f"Invalid packets:        {invalid_packets:,}")
    print(f"Malformed lengths:      {malformed_lengths:,}")
    print(f"Quote updates:          {quote_packets:,}")
    print(f"STREAM_START packets:   {stream_start_packets:,}")
    print(f"STREAM_END packets:     {stream_end_packets:,}")
    print(f"Missing sequences:      {missing_sequences:,}")
    print(f"Duplicate sequences:    {duplicate_sequences:,}")
    print(f"Out-of-order sequences: {out_of_order_sequences:,}")
    print(f"DMA batches completed:  {dma_batches:,}")
    print(f"Packets passed by DMA:  {dma_packets:,}")
    print(f"DMA mismatches:         {mismatched_packets:,}")
    print(f"DMA errors:             {dma_errors:,}")
    print(f"Receive duration:       {receive_duration_s:.6f} s")
    print(f"Observed receive rate:  {receive_rate_pps:,.1f} packets/s")
    print(
        "Planned-count check:   "
        f"{'PASS' if planned_count_matches else 'FAIL'}"
    )
    print(
        "DMA byte comparison:   "
        f"{'PASS' if mismatched_packets == 0 and dma_errors == 0 else 'FAIL'}"
    )

    if mismatch_examples:
        print("\nFirst mismatch examples")
        print("-----------------------")

        for packet_index, expected, received in mismatch_examples:
            print(f"Stream packet {packet_index}")
            print(f"  Expected: {expected}")
            print(f"  Received: {received}")

    print(
        "\nLive end-to-end result: "
        f"{'PASS' if overall_pass else 'FAIL'}"
    )


if __name__ == "__main__":
    main()
