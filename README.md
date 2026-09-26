# PYNQ-Z2 FPGA HFT Pipeline

## Overview

Low-latency market-data processing and trading pipeline emulation developed on a
PYNQ-Z2 using Python, Linux networking, AXI DMA, AXI4-Stream, system verilog and sibling language/s.

Figure 1 illustrates the end-to-end packet flow through the proposed architecture. Market data is generated on the host computer, transmitted over Gigabit Ethernet to the PYNQ-Z2, transferred from the Processing System to the Programmable Logic using AXI DMA, and finally processed by the FPGA trading pipeline.

<p align="center">
  <img src="images/fig1_packet_flow.png"
       alt="Packet Flow Diagram"
       width="850">
</p>

<p align="center">
<b>Figure 1.</b> End-to-end packet flow through the proposed FPGA HFT pipeline.
</p>

## ArchitecturE

Laptop UDP generator
→ PYNQ PS Ethernet
→ Linux/raw socket
→ DDR
→ AXI DMA
→ FPGA parser
→ market-data decoder
→ strategy
→ order generator

## Hardware

- PYNQ-Z2 module
- Zynq-7020
- 1 Gbit Ethernet
- Direct laptop-to-board Ethernet connection
- 16 GB micro SD-card
- USB connection to laptop for power

## Project progress - verification and performance benchmarks are all that is left, everything else is complete

- [x] Phase 1 — Direct Ethernet network setup
- [x] Phase 2 — UDP Communication
- [x] Phase 3 — AXI DMA integration
- [x] Phase 4 — FPGA packet parser 
- [x] Phase 5 — Trading strategy

## Packet format

See `phase2_udp_communication.md` section 2.2 and 2.3. 

## Repository structure

See docs for detailed report of how system works. Any images in md files  can be viewed better by accessing docs/images.

##Complete file path from Sender to final decision

Windows:
phase4_9_live_udp_sender.py
        -> UDP ->
PYNQ Processing System:
phase4_9_live_udp_dma_test.py
        -> AXI DMA MM2S ->
Programmable Logic:
phase5_hft_pipeline.bit
phase5_hft_pipeline.hwh
        -> AXI DMA S2MM ->
PYNQ Processing System:
phase4_9_live_udp_dma_test.py
