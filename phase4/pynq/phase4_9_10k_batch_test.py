#!/usr/bin/env python3
"""Phase 4.9: batched 10,000 packet/s FPGA parser hardware test.

The original stress test submitted every 32-byte packet as a separate DMA
transaction. Python and simple-mode DMA setup overhead limited that approach to
roughly 645 packets/s even though the FPGA datapath was much faster.

This test combines up to 256 HFT1 packets into each DMA transaction. AXI DMA
asserts TLAST once at the end of the complete batch, while the parser uses its
fixed eight-beat word_index counter to recognise each 32-byte packet.
"""

import struct
import time

import numpy as np
from pynq import Overlay, allocate


BITSTREAM_PATH = (
    "/home/xilinx/PYNQ_HFT/phase4_packet_parser/"
    "phase4_packet_parser_2.bit"
)

# True programs the FPGA from Python. Set this to False only when Vivado
# Hardware Manager has already programmed the same bitstream for ILA capture.
DOWNLOAD_OVERLAY = True

TOTAL_PACKETS = 10_000
TARGET_PPS = 10_000
BATCH_PACKETS = 256
PACKET_INTERVAL_NS = 1_000_000_000 // TARGET_PPS

PACKET_STRUCT = struct.Struct("!4sBBBBIQIII")
PACKET_SIZE = PACKET_STRUCT.size
MAX_BATCH_BYTES = BATCH_PACKETS * PACKET_SIZE


def build_packet(packet_index):
    """Create one deterministic and valid 32-byte HFT1 packet."""

    sequence = packet_index + 1
    timestamp_ns = 0x1000000000000000 + sequence

    if packet_index == 0:
        # Stream-start packet describing the test.
        message_type = 4
        side = 0
        instrument_id = TARGET_PPS
        price_ticks = 1_000
        quantity = TOTAL_PACKETS
    elif packet_index == TOTAL_PACKETS - 1:
        # Final stream-end packet.
        message_type = 5
        side = 0
        instrument_id = 0
        price_ticks = 0
        quantity = 0
    else:
        # Valid quote updates alternating between BID=0 and ASK=1.
        message_type = 1
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
    """Busy-wait until an absolute high-resolution deadline."""

    while time.perf_counter_ns() < deadline_ns:
        pass


def compare_batch(expected, received, first_packet_index):
    """Count packet-level mismatches and retain a few diagnostic examples."""

    mismatch_count = 0
    examples = []
    packet_count = len(expected) // PACKET_SIZE

    for local_index in range(packet_count):
        start = local_index * PACKET_SIZE
        stop = start + PACKET_SIZE

        expected_packet = expected[start:stop]
        received_packet = received[start:stop]

        if received_packet != expected_packet:
            mismatch_count += 1

            if len(examples) < 5:
                examples.append(
                    (
                        first_packet_index + local_index,
                        expected_packet.hex(),
                        received_packet.hex(),
                    )
                )

    return mismatch_count, examples


def main():
    total_batches = (
        TOTAL_PACKETS + BATCH_PACKETS - 1
    ) // BATCH_PACKETS

    print("Phase 4.9 - batched 10,000 packet/s parser test")
    print(f"Target packet rate:     {TARGET_PPS:,} packets/s")
    print(f"Packets requested:      {TOTAL_PACKETS:,}")
    print(f"Packets per full batch: {BATCH_PACKETS}")
    print(f"Full batch size:        {MAX_BATCH_BYTES:,} bytes")
    print(f"DMA batches required:   {total_batches}")
    print(f"Download overlay:       {DOWNLOAD_OVERLAY}")

    print("\nPre-generating packet stream...")
    packet_stream = b"".join(
        build_packet(packet_index)
        for packet_index in range(TOTAL_PACKETS)
    )

    if len(packet_stream) != TOTAL_PACKETS * PACKET_SIZE:
        raise RuntimeError("Generated packet stream has an incorrect size")

    print("Loading overlay...")
    overlay = Overlay(
        BITSTREAM_PATH,
        download=DOWNLOAD_OVERLAY,
    )

    print(f"Available IP: {list(overlay.ip_dict.keys())}")
    dma = overlay.axi_dma_0

    # Both buffers can hold the largest 256-packet batch. The nbytes argument
    # restricts the final transfer to its actual 16 packets.
    tx_buffer = allocate(
        shape=(MAX_BATCH_BYTES,),
        dtype=np.uint8,
    )
    rx_buffer = allocate(
        shape=(MAX_BATCH_BYTES,),
        dtype=np.uint8,
    )

    completed_packets = 0
    completed_batches = 0
    mismatched_packets = 0
    dma_errors = 0
    deadline_misses = 0
    maximum_lateness_ns = 0
    mismatch_examples = []

    first_launch_ns = None
    final_completion_ns = None

    try:
        # --------------------------------------------------------------------
        # Warm-up
        #
        # A single packet is still legal in batch mode because its TLAST is
        # correctly aligned with packet beat 7.
        # --------------------------------------------------------------------
        print("\nRunning one warm-up transfer...")
        warmup_packet = packet_stream[:PACKET_SIZE]

        tx_buffer[:PACKET_SIZE] = np.frombuffer(
            warmup_packet,
            dtype=np.uint8,
        )
        rx_buffer[:PACKET_SIZE] = 0

        tx_buffer.flush()
        rx_buffer.flush()

        dma.recvchannel.transfer(
            rx_buffer,
            nbytes=PACKET_SIZE,
        )
        dma.sendchannel.transfer(
            tx_buffer,
            nbytes=PACKET_SIZE,
        )

        dma.sendchannel.wait()
        dma.recvchannel.wait()
        rx_buffer.invalidate()

        if rx_buffer[:PACKET_SIZE].tobytes() != warmup_packet:
            raise RuntimeError("Warm-up DMA byte comparison failed")

        print("Warm-up transfer: PASS")
        print("\nStarting paced batch test...")

        # Packet i is nominally scheduled at:
        #
        #   schedule_start_ns + i * 100 us
        #
        # A complete batch is launched at the deadline of its first packet.
        schedule_start_ns = time.perf_counter_ns() + 5_000_000

        for batch_index in range(total_batches):
            first_packet = batch_index * BATCH_PACKETS
            packet_count = min(
                BATCH_PACKETS,
                TOTAL_PACKETS - first_packet,
            )

            first_byte = first_packet * PACKET_SIZE
            batch_bytes = packet_count * PACKET_SIZE
            last_byte = first_byte + batch_bytes
            expected_batch = packet_stream[first_byte:last_byte]

            tx_buffer[:batch_bytes] = np.frombuffer(
                expected_batch,
                dtype=np.uint8,
            )
            rx_buffer[:batch_bytes] = 0

            tx_buffer.flush()
            rx_buffer.flush()

            # S2MM must be ready before MM2S starts producing stream data.
            dma.recvchannel.transfer(
                rx_buffer,
                nbytes=batch_bytes,
            )

            deadline_ns = (
                schedule_start_ns
                + first_packet * PACKET_INTERVAL_NS
            )
            wait_until(deadline_ns)

            launch_ns = time.perf_counter_ns()

            if first_launch_ns is None:
                first_launch_ns = launch_ns

            lateness_ns = max(0, launch_ns - deadline_ns)
            maximum_lateness_ns = max(
                maximum_lateness_ns,
                lateness_ns,
            )

            # Missing the next full-batch launch interval means the software
            # can no longer sustain the requested average packet rate.
            nominal_batch_interval_ns = (
                packet_count * PACKET_INTERVAL_NS
            )
            if lateness_ns >= nominal_batch_interval_ns:
                deadline_misses += 1

            try:
                dma.sendchannel.transfer(
                    tx_buffer,
                    nbytes=batch_bytes,
                )
                dma.sendchannel.wait()
                dma.recvchannel.wait()
            except Exception as error:
                dma_errors += 1
                print(
                    f"\nDMA error in batch {batch_index}: {error}"
                )
                break

            rx_buffer.invalidate()
            received_batch = rx_buffer[:batch_bytes].tobytes()

            batch_mismatches, examples = compare_batch(
                expected_batch,
                received_batch,
                first_packet,
            )

            mismatched_packets += batch_mismatches
            mismatch_examples.extend(
                examples[: max(0, 10 - len(mismatch_examples))]
            )

            completed_packets += packet_count
            completed_batches += 1

            if (
                completed_batches % 4 == 0
                or completed_packets == TOTAL_PACKETS
            ):
                elapsed_s = (
                    time.perf_counter_ns() - first_launch_ns
                ) / 1_000_000_000
                current_rate = (
                    completed_packets / elapsed_s
                    if elapsed_s > 0
                    else 0.0
                )

                print(
                    f"Progress: {completed_packets:>6,}/"
                    f"{TOTAL_PACKETS:,}  "
                    f"batches={completed_batches:>2}/"
                    f"{total_batches}  "
                    f"rate={current_rate:,.1f} packets/s  "
                    f"mismatches={mismatched_packets}"
                )

        final_completion_ns = time.perf_counter_ns()

    finally:
        tx_buffer.freebuffer()
        rx_buffer.freebuffer()

    if (
        first_launch_ns is not None
        and final_completion_ns is not None
        and final_completion_ns > first_launch_ns
    ):
        duration_s = (
            final_completion_ns - first_launch_ns
        ) / 1_000_000_000
        completion_rate_pps = completed_packets / duration_s
    else:
        duration_s = 0.0
        completion_rate_pps = 0.0

    integrity_pass = (
        completed_packets == TOTAL_PACKETS
        and completed_batches == total_batches
        and mismatched_packets == 0
        and dma_errors == 0
    )

    # One-percent tolerance accommodates ordinary Linux scheduling jitter.
    rate_pass = completion_rate_pps >= TARGET_PPS * 0.99

    print("\nResults")
    print("-------")
    print(f"Packets requested:      {TOTAL_PACKETS:,}")
    print(f"Packets completed:      {completed_packets:,}")
    print(f"DMA batches completed:  {completed_batches}/{total_batches}")
    print(f"Mismatched packets:     {mismatched_packets:,}")
    print(f"DMA errors:             {dma_errors:,}")
    print(f"Batch deadline misses:  {deadline_misses:,}")
    print(
        "Maximum lateness:      "
        f"{maximum_lateness_ns / 1_000:.1f} us"
    )
    print(f"Timed duration:         {duration_s:.6f} s")
    print(
        "Completion rate:       "
        f"{completion_rate_pps:,.1f} packets/s"
    )
    print(
        "Data-integrity check:  "
        f"{'PASS' if integrity_pass else 'FAIL'}"
    )
    print(
        "10,000 pps rate check: "
        f"{'PASS' if rate_pass else 'FAIL'}"
    )

    if mismatch_examples:
        print("\nFirst mismatch examples")
        print("-----------------------")

        for packet_index, expected, received in mismatch_examples:
            print(f"Packet {packet_index}")
            print(f"  Expected: {expected}")
            print(f"  Received: {received}")

    overall_pass = integrity_pass and rate_pass
    print(
        "\nOverall result: "
        f"{'PASS' if overall_pass else 'FAIL'}"
    )


if __name__ == "__main__":
    main()
