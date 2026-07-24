import time

import numpy as np
from pynq import Overlay, allocate


OVERLAY_PATH = (
    "/home/xilinx/PYNQ_HFT/"
    "phase3_passthrough/phase3_passthrough.bit"
)

TRANSFER_COUNT = 1_000
WORDS_PER_TRANSFER = 8
BYTES_PER_TRANSFER = WORDS_PER_TRANSFER * 4


def main():
    print("Loading overlay...")

    overlay = Overlay(OVERLAY_PATH)

    print("Available IP:")
    print(list(overlay.ip_dict.keys()))

    dma = overlay.axi_dma_0

    tx_buffer = allocate(
        shape=(WORDS_PER_TRANSFER,),
        dtype=np.uint32,
    )

    rx_buffer = allocate(
        shape=(WORDS_PER_TRANSFER,),
        dtype=np.uint32,
    )

    successful_transfers = 0
    start_time = time.perf_counter()

    try:
        for transfer_number in range(1, TRANSFER_COUNT + 1):
            # Generate a different deterministic record for each transfer.
            tx_buffer[0] = np.uint32(0x48465431)
            tx_buffer[1] = np.uint32(transfer_number)

            for word_index in range(2, WORDS_PER_TRANSFER):
                value = (
                    transfer_number * 0x1021
                    + word_index * 0x11111111
                ) & 0xFFFFFFFF

                tx_buffer[word_index] = np.uint32(value)

            # A recognizable fill value makes stale RX contents obvious.
            rx_buffer[:] = np.uint32(0xDEADBEEF)

            dma.recvchannel.transfer(rx_buffer)
            dma.sendchannel.transfer(tx_buffer)

            dma.sendchannel.wait()
            dma.recvchannel.wait()

            if not np.array_equal(tx_buffer, rx_buffer):
                print(
                    f"\nFAIL: mismatch during transfer "
                    f"{transfer_number}"
                )

                for index in range(WORDS_PER_TRANSFER):
                    tx_word = int(tx_buffer[index])
                    rx_word = int(rx_buffer[index])

                    if tx_word != rx_word:
                        print(
                            f"Word {index}: "
                            f"TX=0x{tx_word:08X}, "
                            f"RX=0x{rx_word:08X}"
                        )

                return

            successful_transfers += 1

            if transfer_number % 100 == 0:
                print(
                    f"Completed {transfer_number}/"
                    f"{TRANSFER_COUNT} transfers"
                )

        elapsed_time = time.perf_counter() - start_time
        total_bytes = successful_transfers * BYTES_PER_TRANSFER

        print("\nDMA STRESS TEST: PASS")
        print(f"Successful transfers: {successful_transfers}")
        print(f"Total bytes:          {total_bytes}")
        print(f"Elapsed time:         {elapsed_time:.6f} s")
        print(
            f"Transfers per second: "
            f"{successful_transfers / elapsed_time:.2f}"
        )

    finally:
        tx_buffer.freebuffer()
        rx_buffer.freebuffer()


if __name__ == "__main__":
    main()
