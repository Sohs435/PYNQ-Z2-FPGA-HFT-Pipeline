import numpy as np
from pynq import Overlay, allocate


OVERLAY_PATH = (
    "/home/xilinx/PYNQ_HFT/"
    "phase3_passthrough/phase3_passthrough.bit"
)


def main():
    print("Loading overlay...")

    overlay = Overlay(OVERLAY_PATH)

    print("Available IP:")
    print(list(overlay.ip_dict.keys()))

    dma = overlay.axi_dma_0

    # Eight 32-bit words = one 32-byte HFT record.
    tx_buffer = allocate(shape=(8,), dtype=np.uint32)
    rx_buffer = allocate(shape=(8,), dtype=np.uint32)

    try:
        tx_buffer[:] = [
            0x48465431,  # HFT1 magic value
            0x01010000,
            0x00000001,
            0x00000002,
            0x00000003,
            0x00000004,
            0x00000005,
            0x00000006,
        ]

        rx_buffer[:] = 0

        print("\nTransmit buffer:")

        for index, word in enumerate(tx_buffer):
            print(f"TX[{index}] = 0x{int(word):08X}")

        # Start S2MM before MM2S so the receiver is ready before
        # the transmitter begins producing AXI4-Stream data.
        dma.recvchannel.transfer(rx_buffer)
        dma.sendchannel.transfer(tx_buffer)

        dma.sendchannel.wait()
        dma.recvchannel.wait()

        print("\nReceive buffer:")

        for index, word in enumerate(rx_buffer):
            print(f"RX[{index}] = 0x{int(word):08X}")

        if np.array_equal(tx_buffer, rx_buffer):
            print("\nDMA PASSTHROUGH TEST: PASS")
        else:
            print("\nDMA PASSTHROUGH TEST: FAIL")

            for index in range(len(tx_buffer)):
                if tx_buffer[index] != rx_buffer[index]:
                    print(
                        f"Mismatch at word {index}: "
                        f"TX=0x{int(tx_buffer[index]):08X}, "
                        f"RX=0x{int(rx_buffer[index]):08X}"
                    )

    finally:
        tx_buffer.freebuffer()
        rx_buffer.freebuffer()


if __name__ == "__main__":
    main()
