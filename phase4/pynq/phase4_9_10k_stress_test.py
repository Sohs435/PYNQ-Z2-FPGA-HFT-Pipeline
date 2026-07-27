#!/usr/bin/env python3
"""Phase 4.9: 10,000 packet/s FPGA parser stress test.

Each HFT1 packet is submitted as its own 32-byte DMA transaction. This makes
AXI DMA generate TLAST on beat 7 of every packet, as required by the parser.
"""

import struct
import time

import numpy as np
from pynq import Overlay, allocate


BITSTREAM_PATH = (
    "/home/xilinx/PYNQ_HFT/phase4_packet_parser/"
    "phase4_packet_parser.bit"
)

# Keep this False when Vivado has programmed the FPGA and armed the ILA.
# Set it to True when running without Vivado Hardware Manager.
DOWNLOAD_OVERLAY = False

TOTAL_PACKETS = 10_000
TARGET_PPS = 10_000
PACKET_INTERVAL_NS = 1_000_000_000 // TARGET_PPS
PROGRESS_INTERVAL = 1_000

PACKET_STRUCT = struct.Struct("!4sBBBBIQIII")
PACKET_SIZE = PACKET_STRUCT.size


def build_packet(packet_index):
    """Build one valid HFT1 packet with deterministic, checkable fields."""

    sequence = packet_index + 1
    timestamp_ns = 0x1000000000000000 + sequence

    if packet_index == 0:
        # First packet marks the beginning of the test stream.
        message_type = 4
        side = 0
        instrument_id = TARGET_PPS
        price_ticks = 1_000
        quantity = TOTAL_PACKETS
    elif packet_index == TOTAL_PACKETS - 1:
        # Final packet marks the end of the test stream.
        message_type = 5
        side = 0
        instrument_id = 0
        price_ticks = 0
        quantity = 0
    else:
        # Quote updates alternate between BID=0 and ASK=1.
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
        quantity
    )


def wait_until(deadline_ns):
    """Busy-wait until an absolute high-resolution deadline."""

    while time.perf_counter_ns() < deadline_ns:
        pass


def transfer_packet(dma, tx_buffer, rx_buffer, packet):
    """Transfer and return one packet through MM2S -> parser -> FIFO -> S2MM."""

    tx_buffer[:] = np.frombuffer(packet, dtype=np.uint8)
    rx_buffer[:] = 0

    tx_buffer.flush()
    rx_buffer.flush()

    # Always arm S2MM before starting MM2S.
    dma.recvchannel.transfer(rx_buffer)
    dma.sendchannel.transfer(tx_buffer)

    dma.sendchannel.wait()
    dma.recvchannel.wait()

    rx_buffer.invalidate()
    return rx_buffer.tobytes()


def main():
    print("Phase 4.9 - 10,000 packet/s parser stress test")
    print(f"Target packet rate:    {TARGET_PPS:,} packets/s")
    print(f"Packets:               {TOTAL_PACKETS:,}")
    print(f"Packet size:           {PACKET_SIZE} bytes")
    print(f"Packet interval:       {PACKET_INTERVAL_NS:,} ns")
    print(f"Download overlay:      {DOWNLOAD_OVERLAY}")

    print("\nPre-generating packets...")
    packets = [
        build_packet(packet_index)
        for packet_index in range(TOTAL_PACKETS)
    ]

    print("Loading overlay metadata...")
    overlay = Overlay(
        BITSTREAM_PATH,
        download=DOWNLOAD_OVERLAY
    )

    print(f"Available IP: {list(overlay.ip_dict.keys())}")
    dma = overlay.axi_dma_0

    tx_buffer = allocate(
        shape=(PACKET_SIZE,),
        dtype=np.uint8
    )

    rx_buffer = allocate(
        shape=(PACKET_SIZE,),
        dtype=np.uint8
    )

    completed_packets = 0
    mismatched_packets = 0
    dma_errors = 0
    deadline_misses = 0
    maximum_lateness_ns = 0
    mismatch_examples = []

    first_launch_ns = None
    last_launch_ns = None
    final_completion_ns = None

    try:
        print("\nRunning one warm-up transfer...")
        warmup_received = transfer_packet(
            dma,
            tx_buffer,
            rx_buffer,
            packets[0]
        )

        if warmup_received != packets[0]:
            raise RuntimeError("Warm-up DMA byte comparison failed")

        print("Warm-up transfer: PASS")
        print("\nStarting timed test...")

        # A short lead time allows packet 0 to be prepared and S2MM to be armed
        # before the first scheduled MM2S launch.
        schedule_start_ns = time.perf_counter_ns() + 1_000_000

        for packet_index, packet in enumerate(packets):
            tx_buffer[:] = np.frombuffer(packet, dtype=np.uint8)
            rx_buffer[:] = 0

            tx_buffer.flush()
            rx_buffer.flush()

            dma.recvchannel.transfer(rx_buffer)

            deadline_ns = (
                schedule_start_ns
                + packet_index * PACKET_INTERVAL_NS
            )

            wait_until(deadline_ns)

            launch_ns = time.perf_counter_ns()

            if first_launch_ns is None:
                first_launch_ns = launch_ns

            last_launch_ns = launch_ns

            lateness_ns = max(0, launch_ns - deadline_ns)
            maximum_lateness_ns = max(
                maximum_lateness_ns,
                lateness_ns
            )

            # A packet is considered to have missed its time slot if it starts
            # at least one complete packet interval after its deadline.
            if lateness_ns >= PACKET_INTERVAL_NS:
                deadline_misses += 1

            try:
                dma.sendchannel.transfer(tx_buffer)
                dma.sendchannel.wait()
                dma.recvchannel.wait()
            except Exception as error:
                dma_errors += 1
                print(
                    f"\nDMA error at packet {packet_index}: {error}"
                )
                break

            rx_buffer.invalidate()
            received = rx_buffer.tobytes()

            completed_packets += 1

            if received != packet:
                mismatched_packets += 1

                if len(mismatch_examples) < 10:
                    mismatch_examples.append(
                        (
                            packet_index,
                            packet.hex(),
                            received.hex()
                        )
                    )

            if completed_packets % PROGRESS_INTERVAL == 0:
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
                    f"rate={current_rate:,.1f} packets/s  "
                    f"mismatches={mismatched_packets}"
                )

        final_completion_ns = time.perf_counter_ns()

    finally:
        tx_buffer.freebuffer()
        rx_buffer.freebuffer()

    if (
        first_launch_ns is not None
        and last_launch_ns is not None
        and last_launch_ns > first_launch_ns
        and completed_packets > 1
    ):
        launch_duration_s = (
            last_launch_ns - first_launch_ns
        ) / 1_000_000_000

        launch_rate_pps = (
            completed_packets - 1
        ) / launch_duration_s
    else:
        launch_duration_s = 0.0
        launch_rate_pps = 0.0

    if (
        first_launch_ns is not None
        and final_completion_ns is not None
        and final_completion_ns > first_launch_ns
    ):
        completion_duration_s = (
            final_completion_ns - first_launch_ns
        ) / 1_000_000_000

        completion_rate_pps = (
            completed_packets / completion_duration_s
        )
    else:
        completion_duration_s = 0.0
        completion_rate_pps = 0.0

    integrity_pass = (
        completed_packets == TOTAL_PACKETS
        and mismatched_packets == 0
        and dma_errors == 0
    )

    # A one-percent tolerance prevents insignificant Linux scheduling jitter
    # from obscuring whether the system is effectively sustaining the target.
    rate_pass = launch_rate_pps >= TARGET_PPS * 0.99

    print("\nResults")
    print("-------")
    print(f"Packets requested:      {TOTAL_PACKETS:,}")
    print(f"Packets completed:      {completed_packets:,}")
    print(f"Mismatched packets:     {mismatched_packets:,}")
    print(f"DMA errors:             {dma_errors:,}")
    print(f"Deadline misses:        {deadline_misses:,}")
    print(
        "Maximum lateness:      "
        f"{maximum_lateness_ns / 1_000:.1f} us"
    )
    print(f"Launch duration:        {launch_duration_s:.6f} s")
    print(f"Completion duration:    {completion_duration_s:.6f} s")
    print(f"Scheduled launch rate:  {launch_rate_pps:,.1f} packets/s")
    print(f"Completion rate:        {completion_rate_pps:,.1f} packets/s")
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
