#!/usr/bin/env python3
"""Phase 5 end-to-end HOLD/BUY/SELL ILA test for the PYNQ-Z2."""

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
MESSAGE_STREAM_START = 4
MESSAGE_STREAM_END = 5

SIDE_BID = 0
SIDE_ASK = 1

MAGIC = b"HFT1"
VERSION = 1
RESERVED = 0
INSTRUMENT_ID = 1

# A two-tick spread gives a required score of 100 + 2*2 = 104.
BID_PRICE = 10_000
ASK_PRICE = 10_002


def build_packet(
    message_type: int,
    side: int,
    sequence: int,
    timestamp_ns: int,
    instrument_id: int,
    price_ticks: int,
    quantity: int,
) -> bytes:
    """Build one 32-byte HFT1 packet in network byte order."""
    packet = struct.pack(
        PACKET_FORMAT,
        MAGIC,
        VERSION,
        message_type,
        side,
        RESERVED,
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
    """Send one packet through the complete DMA/parser loopback path."""
    tx_buffer = allocate(shape=(len(packet),), dtype=np.uint8)
    rx_buffer = allocate(shape=(len(packet),), dtype=np.uint8)

    try:
        tx_buffer[:] = np.frombuffer(packet, dtype=np.uint8)
        rx_buffer[:] = 0

        # Arm S2MM before MM2S to avoid losing the returning stream.
        dma.recvchannel.transfer(rx_buffer)
        dma.sendchannel.transfer(tx_buffer)

        dma.sendchannel.wait()
        dma.recvchannel.wait()

        received = bytes(rx_buffer)
        if received != packet:
            raise RuntimeError("DMA loopback data mismatch")

        return received
    finally:
        tx_buffer.freebuffer()
        rx_buffer.freebuffer()


def main() -> None:
    print("Phase 5 trading-decision ILA test")
    print("---------------------------------")
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
    print("2. Open the decision ILA, probably hw_ila_2.")
    print("3. Do not arm it yet.")
    print()

    input("Press Enter when Hardware Manager has been refreshed...")

    sequence = 1
    timestamp_ns = 1_000

    def send(
        message_type: int,
        side: int = 0,
        price_ticks: int = 0,
        quantity: int = 0,
        instrument_id: int = INSTRUMENT_ID,
    ) -> None:
        nonlocal sequence, timestamp_ns

        packet = build_packet(
            message_type=message_type,
            side=side,
            sequence=sequence,
            timestamp_ns=timestamp_ns,
            instrument_id=instrument_id,
            price_ticks=price_ticks,
            quantity=quantity,
        )

        dma_transfer(dma, packet)
        sequence += 1
        timestamp_ns += 100

    # Begin a fresh stream. Control-message payload fields are unused by the
    # Phase 5 engine, so they are set to zero here.
    send(MESSAGE_STREAM_START)
    print("STREAM_START sent")

    # Initialize the bid side. No feature is produced yet because the ask side
    # is still absent. The next 32 quote updates all see a complete book and
    # therefore produce exactly 32 eligible feature-engine samples.
    send(
        MESSAGE_QUOTE_UPDATE,
        side=SIDE_BID,
        price_ticks=BID_PRICE,
        quantity=100,
    )

    for sample in range(1, 33):
        side = SIDE_ASK if sample % 2 == 1 else SIDE_BID
        price = ASK_PRICE if side == SIDE_ASK else BID_PRICE

        send(
            MESSAGE_QUOTE_UPDATE,
            side=side,
            price_ticks=price,
            quantity=100,
        )

        if sample % 8 == 0:
            print(f"Warm-up sample {sample}/32")

    print()
    print("Feature-engine warm-up complete")
    print("Expected trend after warm-up: 0")
    print("Expected spread: 2")
    print("Expected required score: 100 + 2*2 = 104")

    print()
    print("HOLD CAPTURE")
    print("------------")
    print("In hw_ila_2 set only:")
    print("signal_valid == 1")
    print("Arm the trigger.")
    input("Press Enter after the HOLD trigger is armed...")

    # The final warm-up update was a bid, so update the ask with the same
    # balanced quantity. The resulting quantity imbalance remains zero.
    send(
        MESSAGE_QUOTE_UPDATE,
        side=SIDE_ASK,
        price_ticks=ASK_PRICE,
        quantity=100,
    )
    print("HOLD packet sent")
    print("Expected: signal=00, score=0, required_score=104")

    input("Review the HOLD capture, then press Enter...")

    print("BUY CAPTURE")
    print("-----------")
    print("Keep only signal_valid == 1 and arm the trigger again.")
    input("Press Enter after the BUY trigger is armed...")

    # bid quantity 300 - ask quantity 100 = +200
    send(
        MESSAGE_QUOTE_UPDATE,
        side=SIDE_BID,
        price_ticks=BID_PRICE,
        quantity=300,
    )
    print("BUY packet sent")
    print("Expected: signal=01, score=200, required_score=104")

    input("Review the BUY capture, then press Enter...")

    print("SELL CAPTURE")
    print("------------")
    print("Keep only signal_valid == 1 and arm the trigger again.")
    input("Press Enter after the SELL trigger is armed...")

    # bid quantity 300 - ask quantity 500 = -200
    send(
        MESSAGE_QUOTE_UPDATE,
        side=SIDE_ASK,
        price_ticks=ASK_PRICE,
        quantity=500,
    )
    print("SELL packet sent")
    print("Expected: signal=10, score=-200, required_score=104")

    input("Review the SELL capture, then press Enter to finish...")

    send(MESSAGE_STREAM_END)
    print()
    print("STREAM_END sent")
    print("All Phase 5.8 decision traffic completed.")


if __name__ == "__main__":
    main()
