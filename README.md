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

## Architecture (still needs to be ironed out properly)

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

## Project progress

- [x] Phase 1 — Direct Ethernet network setup
- [x] Phase 2.1 — UDP Hello World
- [x] Phase 2.2 — Define 32-byte market-data packet
- [x] Phase 2.3 — Send and decode the binary packet
- [x] Phase 2.4 — Continuous market-data stream
- [ ] Phase 2.5 — Sequence and packet-rate testing
- [ ] Phase 3 — AXI DMA integration
- [ ] Phase 4 — FPGA packet parser
- [ ] Phase 5 — Trading strategy
- [ ] Phase 6 — Performance benchmarking

## Packet format

See `phase2_udp_communication.md` section 2.2 and 2.3. 

## Repository structure

idk still need to config it will occur at some point soon 

## Results

Timing, utilization, throughput, and latency results will be added I progress
w/ the proj. 
