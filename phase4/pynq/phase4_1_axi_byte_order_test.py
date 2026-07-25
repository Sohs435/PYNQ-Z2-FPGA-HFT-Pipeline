#!/usr/bin/env python3

import struct

import numpy as np
from pynq import Overlay, allocate


BITSTREAM_PATH = (
    "/home/xilinx/PYNQ_HFT/"
    "phase3_passthrough/phase3_passthrough.bit"
)

PACKET_STRUCT = struct.Struct("!4sBBBBIQIII")
PACKET_SIZE = PACKET_STRUCT.size


def print_packet_mapping(packet):
    print("\nPacket byte mapping")
    print("-------------------")

    for beat in range(8):
        start = beat * 4
        beat_bytes = packet[start:start + 4]

        network_word = int.from_bytes(beat_bytes, byteorder="big")
        expected_tdata = int.from_bytes(beat_bytes, byteorder="little")

        byte_string = " ".join(
            f"{value:02X}" for value in beat_bytes
        )

        tlast = 1 if beat == 7 else 0

        print(
            f"Beat {beat}: "
            f"bytes={byte_string}  "
            f"network_word=0x{network_word:08X}  "
            f"expected_TDATA=0x{expected_tdata:08X}  "
            f"TLAST={tlast}"
        )


def main():
    print("Phase 4.1 — AXI byte-order test")
    print(f"Packet size: {PACKET_SIZE} bytes")

    packet = PACKET_STRUCT.pack(
        b"HFT1",                    # Magic
        1,                          # Version
        1,                          # Message type: quote update
        1,                          # Side
        0,                          # Reserved
        0x01020304,                 # Sequence
        0x1112131415161718,         # Timestamp
        0x21222324,                 # Instrument ID
        0x31323334,                 # Price ticks
        0x41424344                  # Quantity
    )

    assert len(packet) == 32

    print_packet_mapping(packet)

    print("\nLoading Phase 3 pass-through overlay...")
    overlay = Overlay(BITSTREAM_PATH)

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

    try:
        tx_buffer[:] = np.frombuffer(
            packet,
            dtype=np.uint8
        )

        rx_buffer[:] = 0

        tx_buffer.flush()

        print("\nStarting DMA transfer...")

        # Always start S2MM before MM2S.
        dma.recvchannel.transfer(rx_buffer)
        dma.sendchannel.transfer(tx_buffer)

        dma.sendchannel.wait()
        dma.recvchannel.wait()

        rx_buffer.invalidate()

        received = rx_buffer.tobytes()

        print("\nTransmitted bytes")
        print("-----------------")
        print(packet.hex(" "))

        print("\nReceived bytes")
        print("--------------")
        print(received.hex(" "))

        if received == packet:
            print("\nDMA byte comparison: PASS")
        else:
            print("\nDMA byte comparison: FAIL")

            for index, (expected, actual) in enumerate(
                zip(packet, received)
            ):
                if expected != actual:
                    print(
                        f"Byte {index}: "
                        f"expected=0x{expected:02X}, "
                        f"received=0x{actual:02X}"
                    )

        print("\nReceived AXI-word interpretation")
        print("--------------------------------")

        for beat in range(8):
            start = beat * 4
            beat_bytes = received[start:start + 4]

            axis_word = int.from_bytes(
                beat_bytes,
                byteorder="little"
            )

            print(
                f"Beat {beat}: "
                f"TDATA=0x{axis_word:08X}"
            )

    finally:
        tx_buffer.freebuffer()
        rx_buffer.freebuffer()


if __name__ == "__main__":
    main()
