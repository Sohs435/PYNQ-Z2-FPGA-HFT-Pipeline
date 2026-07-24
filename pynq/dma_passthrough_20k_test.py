"""Validate a batched logical rate of 20,000 32-byte records per second."""

import time

import numpy as np
from pynq import Overlay, allocate


OVERLAY_PATH = (
    "/home/xilinx/PYNQ_HFT/"
    "phase3_passthrough/phase3_passthrough.bit"
)

TARGET_PPS = 20_000
DURATION_SECONDS = 10.0

PACKET_WORDS = 8
PACKET_BYTES = PACKET_WORDS * 4

BATCH_PACKETS = 256
BATCH_WORDS = BATCH_PACKETS * PACKET_WORDS
BATCH_BYTES = BATCH_PACKETS * PACKET_BYTES

TOTAL_BATCHES = int(
    TARGET_PPS * DURATION_SECONDS // BATCH_PACKETS
)

PLANNED_PACKETS = TOTAL_BATCHES * BATCH_PACKETS


def main():
    print("Loading overlay...")

    overlay = Overlay(OVERLAY_PATH)

    print("Available IP:")
    print(list(overlay.ip_dict.keys()))

    dma = overlay.axi_dma_0

    print(f"\nTarget packet rate:  {TARGET_PPS:,} packets/s")
    print(f"Target duration:     {DURATION_SECONDS:.1f} s")
    print(f"Packets per batch:   {BATCH_PACKETS}")
    print(f"Bytes per batch:     {BATCH_BYTES:,}")
    print(f"DMA batches:         {TOTAL_BATCHES}")
    print(f"Planned packets:     {PLANNED_PACKETS:,}")

    tx_buffer = allocate(
        shape=(BATCH_WORDS,),
        dtype=np.uint32,
    )

    rx_buffer = allocate(
        shape=(BATCH_WORDS,),
        dtype=np.uint32,
    )

    tx_packets = tx_buffer.reshape(
        BATCH_PACKETS,
        PACKET_WORDS,
    )

    packets_completed = 0
    missed_deadlines = 0

    start_time = time.perf_counter()

    try:
        for batch_number in range(TOTAL_BATCHES):
            first_sequence = (
                batch_number * BATCH_PACKETS
            ) + 1

            sequences = np.arange(
                first_sequence,
                first_sequence + BATCH_PACKETS,
                dtype=np.uint32,
            )

            # Construct 256 deterministic 32-byte records.
            tx_packets[:, 0] = np.uint32(0x48465431)
            tx_packets[:, 1] = sequences
            tx_packets[:, 2] = (
                sequences ^ np.uint32(0xA5A5A5A5)
            )
            tx_packets[:, 3] = (
                sequences + np.uint32(100_000)
            )
            tx_packets[:, 4] = np.uint32(100)
            tx_packets[:, 5] = (
                sequences ^ np.uint32(0x12345678)
            )
            tx_packets[:, 6] = (
                sequences ^ np.uint32(0x87654321)
            )
            tx_packets[:, 7] = (
                sequences ^ np.uint32(0xFFFFFFFF)
            )

            rx_buffer[:] = np.uint32(0xDEADBEEF)

            dma.recvchannel.transfer(rx_buffer)
            dma.sendchannel.transfer(tx_buffer)

            dma.sendchannel.wait()
            dma.recvchannel.wait()

            if not np.array_equal(tx_buffer, rx_buffer):
                print(
                    f"\nFAIL: data mismatch in DMA batch "
                    f"{batch_number}"
                )

                mismatch_indices = np.flatnonzero(
                    tx_buffer != rx_buffer
                )

                for index in mismatch_indices[:10]:
                    print(
                        f"Word {int(index)}: "
                        f"TX=0x{int(tx_buffer[index]):08X}, "
                        f"RX=0x{int(rx_buffer[index]):08X}"
                    )

                return

            packets_completed += BATCH_PACKETS

            # Pace against an absolute deadline so timing error does
            # not accumulate across the complete test.
            next_deadline = (
                start_time
                + packets_completed / TARGET_PPS
            )

            remaining_time = (
                next_deadline - time.perf_counter()
            )

            if remaining_time > 0:
                time.sleep(remaining_time)
            else:
                missed_deadlines += 1

            if (batch_number + 1) % 100 == 0:
                print(
                    f"Completed {packets_completed:,}/"
                    f"{PLANNED_PACKETS:,} packets"
                )

        elapsed_time = time.perf_counter() - start_time
        measured_pps = packets_completed / elapsed_time
        total_bytes = packets_completed * PACKET_BYTES

        print("\n20K PACKET-RATE TEST RESULTS")
        print(f"Packets completed:   {packets_completed:,}")
        print(f"Total bytes:         {total_bytes:,}")
        print(f"Elapsed time:        {elapsed_time:.6f} s")
        print(f"Measured rate:       {measured_pps:,.2f} packets/s")
        print(f"Missed deadlines:    {missed_deadlines}")

        if measured_pps >= TARGET_PPS * 0.95:
            print("Result:              PASS")
        else:
            print("Result:              FAIL - rate below tolerance")

    finally:
        tx_buffer.freebuffer()
        rx_buffer.freebuffer()


if __name__ == "__main__":
    main()
