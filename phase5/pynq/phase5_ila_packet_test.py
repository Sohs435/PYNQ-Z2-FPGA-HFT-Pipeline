#!/usr/bin/env python3
"""Phase 5 parser-validation test for the PYNQ-Z2.

The script sends one valid HFT1 packet and one packet with invalid magic
through the AXI DMA loopback. Vivado ILA captures are used to verify the
parser's packet_valid, packet_error, and error_flags outputs.
"""

from pathlib import Path
import struct

import numpy as np
from pynq import Overlay, allocate


BITSTREAM_PATH = Path(
    "/home/xilinx/PYNQ_HFT/phase5/phase5_hft_pipeline.bit"
)

PACKET_FORMAT = "!4sBBBBIQIII"
PACKET_SIZE = struct.calcsize(PACKET_FORMAT)

MESSAGE_QUOTE_UPDATE = 1


def build_packet(
    magic: bytes,
    version: int,
    message_type: int,
    side: int,
    reserved: int,
    sequence: int,
    timestamp_ns: int,
    instrument_id: int,
    price_ticks: int,
    quantity: int,
) -> bytes:
    """Build one 32-byte, big-endian HFT1 packet."""
    packet = struct.pack(
        PACKET_FORMAT,
        magic,
        version,
        message_type,
        side,
        reserved,
        sequence,
        timestamp_ns,
        instrument_id,
        price_ticks,
        quantity,
    )

    if len(packet) != PACKET_SIZE:
        raise RuntimeError(f"Expected {PACKET_SIZE} bytes, got {len(packet)}")

    return packet


def dma_transfer(dma, packet: bytes) -> bytes:
    """Transfer one packet through MM2S -> parser -> S2MM."""
    tx_buffer = allocate(shape=(len(packet),), dtype=np.uint8)
    rx_buffer = allocate(shape=(len(packet),), dtype=np.uint8)

    try:
        tx_buffer[:] = np.frombuffer(packet, dtype=np.uint8)
        rx_buffer[:] = 0

        # Start S2MM first so the returning AXI stream has a destination.
        dma.recvchannel.transfer(rx_buffer)
        dma.sendchannel.transfer(tx_buffer)

        dma.sendchannel.wait()
        dma.recvchannel.wait()

        return bytes(rx_buffer)
    finally:
        tx_buffer.freebuffer()
        rx_buffer.freebuffer()


def send_and_check(dma, name: str, packet: bytes) -> None:
    """Send a packet and confirm that the DMA loopback is byte-exact."""
    received = dma_transfer(dma, packet)

    if received != packet:
        raise RuntimeError(f"{name}: DMA loopback data mismatch")

    print(f"{name} packet sent; DMA loopback matched all {len(packet)} bytes")


def main() -> None:
    print("Phase 5 parser ILA test")
    print("-----------------------")
    print(f"Bitstream: {BITSTREAM_PATH}")
    print()

    if not BITSTREAM_PATH.is_file():
        raise FileNotFoundError(BITSTREAM_PATH)

    overlay = Overlay(str(BITSTREAM_PATH), download=True)
    dma = overlay.axi_dma_0

    print("Overlay loaded")
    print(f"Available IP: {list(overlay.ip_dict.keys())}")
    print()
    print("In Vivado Hardware Manager:")
    print("1. Refresh the programmed device.")
    print("2. Open the parser ILA.")
    print("3. Do not arm it yet.")
    print()

    input("Press Enter when Hardware Manager has been refreshed...")

    valid_packet = build_packet(
        magic=b"HFT1",
        version=1,
        message_type=MESSAGE_QUOTE_UPDATE,
        side=0,
        reserved=0,
        sequence=1,
        timestamp_ns=1_000,
        instrument_id=1,
        price_ticks=10_000,
        quantity=100,
    )

    print()
    print("VALID PACKET CAPTURE")
    print("--------------------")
    print("Set packet_valid == 1 in the parser ILA and arm the trigger.")
    input("Press Enter after the valid-packet trigger is armed...")
    send_and_check(dma, "Valid", valid_packet)
    print("Expected: packet_valid=1, packet_error=0, error_flags=0x00")

    input("Review the valid capture, then press Enter...")

    invalid_magic_packet = build_packet(
        magic=b"BAD1",
        version=1,
        message_type=MESSAGE_QUOTE_UPDATE,
        side=0,
        reserved=0,
        sequence=2,
        timestamp_ns=2_000,
        instrument_id=1,
        price_ticks=10_000,
        quantity=100,
    )

    print()
    print("INVALID MAGIC CAPTURE")
    print("---------------------")
    print("Set packet_error == 1 in the parser ILA and arm the trigger.")
    input("Press Enter after the invalid-packet trigger is armed...")
    send_and_check(dma, "Invalid-magic", invalid_magic_packet)
    print("Expected: packet_valid=0, packet_error=1, error_flags=0x01")

    input("Review the invalid capture, then press Enter to finish...")
    print()
    print("All Phase 5 parser-validation traffic completed.")


if __name__ == "__main__":
    main()
