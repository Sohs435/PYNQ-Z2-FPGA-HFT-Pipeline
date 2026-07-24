# Phase 3 — AXI DMA Communication and Programmable-Logic Integration

**Platform:** PYNQ-Z2, Zynq-7000  
**Tools:** Vivado, SystemVerilog, PYNQ Python, AXI DMA  
**Status:** AXI DMA loopback proven; AXI4-Stream pass-through RTL designed and behaviourally verified; hardware insertion of the custom RTL block remains  
**Last updated:** 24 July 2026

## 3.1 Phase objective

The purpose of Phase 3 is to establish a reliable communication path between the Processing System (PS) and Programmable Logic (PL) of the PYNQ-Z2. This is the point where the HFT pipeline moves beyond software-only UDP reception and begins transferring market-data packets into FPGA logic for hardware processing.

The target data path is: Laptop UDP sender -> PYNQ Ethernet PHY and PS Gigabit Ethernet MAC -> Linux UDP socket -> PS DDR transmit buffer -> AXI DMA MM2S channel
-> AXI4-Stream packet-processing RTL in the PL -> AXI DMA S2MM channel -> PS DDR receive buffer -> Python validation


The Ethernet interface on the PYNQ-Z2 is connected to the Zynq Processing System rather than directly to the Programmable Logic. Linux therefore receives the UDP packets first. The packet bytes must then be placed in a PS DDR buffer and transferred to the PL through AXI DMA.

Phase 3 is concerned with this PS-to-PL and PL-to-PS transfer. The custom market-data processing itself will be added after the communication path has been proven reliable.

## 3.2 AXI interfaces used in the design

The design uses more than one form of AXI. These interfaces have different jobs and should not be treated as interchangeable.

### 3.2.1 AXI4 memory-mapped

AXI4 memory-mapped communication addresses locations in a memory space. The AXI DMA uses memory-mapped transactions to read input data from PS DDR and write processed data back to PS DDR.

The DMA performs these transfers:

```text
MM2S: PS DDR memory → AXI DMA
S2MM: AXI DMA → PS DDR memory
```

The CPU does not manually drive the low-level AXI read and write handshakes. The AXI DMA IP and AXI interconnect generate those transactions after software gives the DMA a buffer address and transfer length.

### 3.2.2 AXI4-Lite

AXI4-Lite is used as a control interface. Python accesses the DMA control and status registers through the Processing System and the AXI-Lite connection.

Software uses this path to provide information such as:

- The physical address of the transmit buffer
- The physical address of the receive buffer
- The number of bytes to transfer
- Whether a channel should start
- DMA status and completion information

The Zynq PS `M_AXI_GP0` interface is suitable for this control path because the processor is the AXI master and the DMA register interface is the controlled AXI slave.

### 3.2.3 AXI4-Stream

AXI4-Stream transfers an ordered sequence of data words without providing a memory address for every word. It is the interface used between the DMA and the custom PL processing block.

For a 32-bit AXI4-Stream configuration, every accepted transfer carries one 32-bit word:

```text
MM2S M_AXIS → custom RTL S_AXIS
custom RTL M_AXIS → S2MM S_AXIS
```

The essential AXI4-Stream signals used by the current module are:

| Signal | Driven by | Purpose |
| --- | --- | --- |
| `TDATA` | Source | Carries the current data word |
| `TVALID` | Source | Indicates that `TDATA` contains a valid word |
| `TREADY` | Destination | Indicates that the destination can accept the word |
| `TLAST` | Source | Marks the final word of the current packet or DMA transfer |

An AXI4-Stream transfer occurs only on a rising clock edge where both of the following are high:

```systemverilog
tvalid && tready
```

`TVALID` and `TREADY` are independent. The source is allowed to assert `TVALID` before the destination asserts `TREADY`. If that happens, the source must keep `TDATA`, `TVALID`, `TLAST`, and any other sideband signals stable until the destination accepts the transfer.

## 3.3 Initial Vivado hardware platform

The first Vivado block design established a baseline DMA loopback before introducing custom RTL.

The design contained:

- ZYNQ7 Processing System
- AXI DMA
- AXI interconnect or SmartConnect infrastructure
- Processor System Reset infrastructure
- PS DDR connection
- AXI DMA MM2S and S2MM channels
- A direct AXI4-Stream loopback from MM2S to S2MM

The validated baseline stream path was: Python transmit array -> PS DDR -> AXI DMA MM2S -> Direct AXI4-Stream connection -> AXI DMA S2MM -> PS DDR -> Python receive array


The direct stream loopback deliberately contained no packet-processing RTL. Its only purpose was to prove that the Processing System, DDR memory, DMA channels, AXI interfaces, overlay metadata, and Python runtime could operate together.

![AXI4-Stream pass-through behavioural simulation](images/block_diagram_phase3.png)

*Figure 3.1: Block Diagram*
## 3.4 Bitstream and overlay generation

After validating the block design, Vivado generated the HDL wrapper and FPGA bitstream.

Two files are required by PYNQ:

| File | Purpose |
| --- | --- |
| `.bit` | Contains the FPGA configuration data loaded into the PL |
| `.hwh` | Describes the hardware design, IP names, register maps, addresses, interrupts, and other metadata used by PYNQ |

The `.bit` and `.hwh` files must describe the same Vivado build and should use the same base filename. Using an old `.hwh` file with a new bitstream can cause PYNQ to expose incorrect IP names or register addresses.

The generated wrapper was kept as SystemVerilog. The completed overlay exposed:

```text
axi_dma_0
processing_system7_0
```

This confirmed that PYNQ could identify the DMA and Processing System from the hardware metadata.

## 3.5 PYNQ runtime setup and troubleshooting

The initial overlay tests encountered several software-environment problems. These were runtime problems rather than failures in the AXI hardware design.

### 3.5.1 XRT device error

An early attempt produced:

```text
Could not open device index 0
```

This indicated that the Python/XRT environment was not successfully opening the programmable device. Kernel inspection later showed that the `zocl` DRM driver had initialized and that KDS clients were being created, confirming that the kernel-side FPGA runtime was present.

### 3.5.2 Missing Python dependency

Another attempt failed with:

```text
No module named pydantic
```

The PYNQ image contained a dedicated Python virtual environment with the required packages. The correct interpreter was:

```text
/usr/local/share/pynq-venv/bin/python3
```

The working execution form was therefore based on:

```bash
sudo -E /usr/local/share/pynq-venv/bin/python3 dma_loopback_test.py
```

Using the correct environment allowed the PYNQ overlay and DMA libraries to load consistently.

### 3.5.3 Meaning of the fix

The fact that changing the Python environment resolved the failure is important. It separates two possible classes of fault:

- A hardware fault, such as an invalid bitstream, incorrect address map, missing DMA connection, or clock/reset problem
- A software-environment fault, such as importing the wrong PYNQ installation or missing Python dependencies

The successful DMA transfer later confirmed that the underlying Vivado hardware platform was operational.

## 3.6 Baseline DMA loopback validation

The DMA loopback test allocated physically contiguous buffers in PS DDR, filled the transmit buffer, started the S2MM receive channel, and then started the MM2S transmit channel.

Starting S2MM first is useful because it ensures that the receiving side is prepared before MM2S begins producing stream data. AXI4-Stream backpressure should still prevent data loss if the receiver is temporarily unready, but enabling the receive path first simplifies initial testing.

A representative Python structure is:

```python
import numpy as np
from pynq import Overlay, allocate

overlay = Overlay("/path/to/dma_loopback.bit")
dma = overlay.axi_dma_0

tx_buffer = allocate(shape=(8,), dtype=np.uint32)
rx_buffer = allocate(shape=(8,), dtype=np.uint32)

tx_buffer[:] = [
    0x48465431,
    0x01010000,
    0x00000001,
    0x00000000,
    0x00000000,
    0x00000000,
    0x00000000,
    0x00000000,
]

rx_buffer[:] = 0

dma.recvchannel.transfer(rx_buffer)
dma.sendchannel.transfer(tx_buffer)

dma.sendchannel.wait()
dma.recvchannel.wait()

assert np.array_equal(tx_buffer, rx_buffer)

tx_buffer.freebuffer()
rx_buffer.freebuffer()
```

The eight 32-bit words occupy 32 bytes, matching the current HFT packet size. The first word:

```text
0x48465431
```

is the ASCII representation of the packet magic value `HFT1`.

The loopback test passed. This proved all of the following:

- Python could allocate DMA-compatible contiguous buffers
- The overlay could be loaded
- PYNQ could locate `axi_dma_0`
- MM2S could read the transmit buffer from PS DDR
- AXI4-Stream data could cross the PL
- S2MM could write the received stream to PS DDR
- Python could read back the received data
- The two DMA channels could complete without hanging

This was the first end-to-end proof of PS-to-PL-to-PS data movement.

## 3.7 Custom AXI4-Stream pass-through block

After validating the direct DMA loopback, a custom registered AXI4-Stream block was created. The block currently performs no market-data transformation. It stores each accepted word in a one-word output register and forwards it to S2MM.

This apparently simple block is important because it establishes the exact handshake structure that later packet-processing logic must preserve.

### 3.7.1 Module interface

```systemverilog
module axis_passthrough #(
    parameter DATA_WIDTH = 32
) (
    input  logic                  aclk,
    input  logic                  aresetn,

    input  logic [DATA_WIDTH-1:0] s_axis_tdata,
    input  logic                  s_axis_tvalid,
    output logic                  s_axis_tready,
    input  logic                  s_axis_tlast,

    output logic [DATA_WIDTH-1:0] m_axis_tdata,
    output logic                  m_axis_tvalid,
    input  logic                  m_axis_tready,
    output logic                  m_axis_tlast
);

    assign s_axis_tready = !m_axis_tvalid || m_axis_tready;

    always_ff @(posedge aclk) begin
        if (!aresetn) begin
            m_axis_tdata  <= '0;
            m_axis_tvalid <= 1'b0;
            m_axis_tlast  <= 1'b0;
        end else if (s_axis_tready) begin
            m_axis_tvalid <= s_axis_tvalid;

            if (s_axis_tvalid) begin
                m_axis_tdata <= s_axis_tdata;
                m_axis_tlast <= s_axis_tlast;
            end
        end
    end

endmodule
```

### 3.7.2 Direction of the two stream interfaces

The naming is from the perspective of the custom module:

```text
AXI DMA MM2S M_AXIS
        ↓
custom module S_AXIS
        ↓ internal register
custom module M_AXIS
        ↓
AXI DMA S2MM S_AXIS
```

The custom block is an AXI4-Stream slave on its input because it receives data from MM2S. It is an AXI4-Stream master on its output because it produces data for S2MM.

`S_AXIS` does not mean that the signals should be zero. It describes which side of the interface receives the stream. The receiving S2MM `S_AXIS` interface expects the custom block to assert `m_axis_tvalid` whenever the custom block has valid output data.

### 3.7.3 The output register

The module contains one logical storage location:

```text
m_axis_tdata
m_axis_tlast
m_axis_tvalid
```

`m_axis_tvalid` also acts as the occupancy flag:

```text
m_axis_tvalid = 0 → output register is empty
m_axis_tvalid = 1 → output register contains a valid word
```

The actual values of `m_axis_tdata` and `m_axis_tlast` do not matter while `m_axis_tvalid` is zero. AXI uses `TVALID` to distinguish meaningful data from stale register contents.

### 3.7.4 Ready-generation equation

The central combinational expression is:

```systemverilog
assign s_axis_tready = !m_axis_tvalid || m_axis_tready;
```

This can be read as:

```text
Input ready = output register empty OR current output being drained
```

The module can accept a new input word in either of two situations.

#### Situation A: the output register is empty

If:

```text
m_axis_tvalid = 0
```

then:

```text
s_axis_tready = 1
```

The module has free internal storage. It can accept one word from MM2S even if S2MM is not currently ready. The word will be held in the output register until S2MM eventually asserts `m_axis_tready`.

#### Situation B: the current output is being accepted

If:

```text
m_axis_tvalid = 1
m_axis_tready = 1
```

then the existing output word will be accepted by S2MM on the next rising edge. The custom module can simultaneously accept a new MM2S word and use it to replace the departing output word.

This simultaneous drain-and-replacement behaviour allows a sustained throughput of one 32-bit word per clock cycle.

#### Situation C: the output is stalled

If:

```text
m_axis_tvalid = 1
m_axis_tready = 0
```

then:

```text
s_axis_tready = 0
```

The output register is full and S2MM is not accepting it. The custom module must stop MM2S because accepting another input would overwrite the stalled output word.

The complete truth table is:

| `m_axis_tvalid` | `m_axis_tready` | Register condition | `s_axis_tready` |
| ---: | ---: | --- | ---: |
| 0 | 0 | Empty | 1 |
| 0 | 1 | Empty | 1 |
| 1 | 0 | Full and stalled | 0 |
| 1 | 1 | Full and being drained | 1 |

Using only:

```systemverilog
assign s_axis_tready = !m_axis_tvalid;
```

would prevent simultaneous drain and replacement. It would introduce an empty cycle between transfers and limit the stage to one word every two clocks. Including `m_axis_tready` avoids that unnecessary throughput loss.

### 3.7.5 Sequential register behaviour

The sequential block runs on the rising edge of `aclk`:

```systemverilog
always_ff @(posedge aclk)
```

The reset is active-low and synchronous. Bringing `aresetn` low does not immediately change the registers; the registers are cleared on the next rising edge:

```systemverilog
if (!aresetn) begin
    m_axis_tdata  <= '0;
    m_axis_tvalid <= 1'b0;
    m_axis_tlast  <= 1'b0;
end
```

Clearing `m_axis_tvalid` is the essential reset operation because it marks the output register as empty.

When `s_axis_tready` is high, the output register is allowed to change:

```systemverilog
else if (s_axis_tready)
```

If `s_axis_tvalid` is also high, an input handshake occurs and the module stores the incoming word:

```systemverilog
m_axis_tvalid <= s_axis_tvalid;

if (s_axis_tvalid) begin
    m_axis_tdata <= s_axis_tdata;
    m_axis_tlast <= s_axis_tlast;
end
```

If `s_axis_tvalid` is low while `s_axis_tready` is high, no replacement word is arriving. `m_axis_tvalid` is therefore cleared, marking the register empty after the previous word has left.

When `s_axis_tready` is low, the sequential block performs no assignments. Nonblocking-assignment semantics cause all output registers to retain their previous values. This is precisely the behaviour required during backpressure.

### 3.7.6 `TLAST` propagation

`TLAST` marks the final word in a DMA transfer. It must remain paired with the corresponding `TDATA` word.

The module therefore captures both signals in the same condition:

```systemverilog
if (s_axis_tvalid) begin
    m_axis_tdata <= s_axis_tdata;
    m_axis_tlast <= s_axis_tlast;
end
```

Because the block is registered, the output data and output `TLAST` appear one pipeline stage after the input handshake. If S2MM introduces backpressure, both remain stable together until the output handshake completes.

Failure to propagate `TLAST` can cause S2MM to wait indefinitely for the end of a transfer, which may cause a Python call such as `recvchannel.wait()` to hang.

### 3.7.7 `TKEEP` integration check

The current behavioural module uses complete 32-bit words, and the 32-byte HFT packet contains exactly eight such words. No partial final word is required.

When the RTL is inserted into the Vivado block design, the DMA interfaces must be inspected for `TKEEP`. If `TKEEP` is enabled, it must either:

- Be passed through the custom module alongside `TDATA` and `TLAST`, or
- Be tied to `4'b1111` for a 32-bit stream when every byte of every word is valid

A generic pass-through version would use:

```systemverilog
input  logic [(DATA_WIDTH/8)-1:0] s_axis_tkeep;
output logic [(DATA_WIDTH/8)-1:0] m_axis_tkeep;
```

and register `s_axis_tkeep` using the same enable condition as `TDATA` and `TLAST`.

## 3.8 Behavioural simulation

The pass-through module was tested in Vivado using a SystemVerilog behavioural testbench. The purpose of the simulation was not merely to show that data could pass through under ideal conditions. It specifically exercised the backpressure rule that protects a stalled output word from being overwritten.

### 3.8.1 Test sequence

The simulation performed the following tests:

1. Assert reset and verify that `m_axis_tvalid` clears.
2. Send `0x11111111` with the output ready and verify a normal transfer.
3. Send `0x22222222` while the previous word leaves, verifying simultaneous drain and replacement.
4. Deassert `m_axis_tready` while `0x22222222` is stored.
5. Attempt to send `0x33333333` during the stall.
6. Verify that `s_axis_tready` falls and that the stored output remains unchanged.
7. Reassert `m_axis_tready`.
8. Verify that `0x22222222` leaves and `0x33333333` replaces it.
9. Remove input valid and verify that the output register becomes empty.

### 3.8.2 Testbench

```systemverilog
`timescale 1ns / 1ps

module axis_passthrough_tb;

    localparam DATA_WIDTH = 32;

    logic                  aclk;
    logic                  aresetn;

    logic [DATA_WIDTH-1:0] s_axis_tdata;
    logic                  s_axis_tvalid;
    logic                  s_axis_tready;
    logic                  s_axis_tlast;

    logic [DATA_WIDTH-1:0] m_axis_tdata;
    logic                  m_axis_tvalid;
    logic                  m_axis_tready;
    logic                  m_axis_tlast;

    axis_passthrough #(
        .DATA_WIDTH(DATA_WIDTH)
    ) dut (
        .aclk          (aclk),
        .aresetn       (aresetn),

        .s_axis_tdata  (s_axis_tdata),
        .s_axis_tvalid (s_axis_tvalid),
        .s_axis_tready (s_axis_tready),
        .s_axis_tlast  (s_axis_tlast),

        .m_axis_tdata  (m_axis_tdata),
        .m_axis_tvalid (m_axis_tvalid),
        .m_axis_tready (m_axis_tready),
        .m_axis_tlast  (m_axis_tlast)
    );

    always #5 aclk = ~aclk;

    initial begin
        aclk          = 1'b0;
        aresetn       = 1'b0;

        s_axis_tdata  = '0;
        s_axis_tvalid = 1'b0;
        s_axis_tlast  = 1'b0;

        m_axis_tready = 1'b0;

        repeat (3) @(posedge aclk);
        #1;

        if (m_axis_tvalid !== 1'b0)
            $fatal(1, "RESET FAILED: m_axis_tvalid should be 0");

        @(negedge aclk);
        aresetn       = 1'b1;
        m_axis_tready = 1'b1;

        s_axis_tdata  = 32'h1111_1111;
        s_axis_tvalid = 1'b1;
        s_axis_tlast  = 1'b0;

        @(posedge aclk);
        #1;

        if (m_axis_tvalid !== 1'b1)
            $fatal(1, "NORMAL TRANSFER FAILED: output valid is not 1");

        if (m_axis_tdata !== 32'h1111_1111)
            $fatal(1, "NORMAL TRANSFER FAILED: incorrect output data");

        if (m_axis_tlast !== 1'b0)
            $fatal(1, "NORMAL TRANSFER FAILED: TLAST should be 0");

        @(negedge aclk);
        s_axis_tdata = 32'h2222_2222;
        s_axis_tlast = 1'b1;

        @(posedge aclk);
        #1;

        if (m_axis_tdata !== 32'h2222_2222)
            $fatal(1, "REPLACEMENT FAILED: second word not loaded");

        if (m_axis_tlast !== 1'b1)
            $fatal(1, "REPLACEMENT FAILED: TLAST not copied");

        // Backpressure begins.
        @(negedge aclk);
        m_axis_tready = 1'b0;
        s_axis_tdata  = 32'h3333_3333;
        s_axis_tlast  = 1'b0;

        #1;

        if (s_axis_tready !== 1'b0)
            $fatal(1, "BACKPRESSURE FAILED: input ready should be 0");

        repeat (2) begin
            @(posedge aclk);
            #1;

            if (m_axis_tdata !== 32'h2222_2222)
                $fatal(1, "BACKPRESSURE FAILED: output data changed");

            if (m_axis_tvalid !== 1'b1)
                $fatal(1, "BACKPRESSURE FAILED: output valid changed");

            if (m_axis_tlast !== 1'b1)
                $fatal(1, "BACKPRESSURE FAILED: TLAST changed");
        end

        // Backpressure ends.
        @(negedge aclk);
        m_axis_tready = 1'b1;

        @(posedge aclk);
        #1;

        if (m_axis_tdata !== 32'h3333_3333)
            $fatal(1, "DRAIN FAILED: waiting word not captured");

        if (m_axis_tvalid !== 1'b1)
            $fatal(1, "DRAIN FAILED: output should remain valid");

        @(negedge aclk);
        s_axis_tvalid = 1'b0;
        s_axis_tlast  = 1'b0;

        @(posedge aclk);
        #1;

        if (m_axis_tvalid !== 1'b0)
            $fatal(1, "FINISH FAILED: output valid should clear");

        $display("ALL AXI4-STREAM TESTS PASSED");

        #20;
        $finish;
    end

endmodule
```

### 3.8.3 Simulation result

The waveform showed the expected sequence:

```text
0x11111111 → normal transfer
0x22222222 → stored and then held during backpressure
0x33333333 → accepted after backpressure ended
```

The most important interval occurred at approximately 50–70 ns:

```text
m_axis_tready = 0
m_axis_tvalid = 1
s_axis_tready = 0
m_axis_tdata  = 0x22222222
m_axis_tlast  = 1
```

Throughout that interval, `m_axis_tdata`, `m_axis_tvalid`, and `m_axis_tlast` remained stable. This proved that the module did not overwrite the stalled output word.

When `m_axis_tready` returned high at approximately 70 ns:

- `s_axis_tready` also returned high
- S2MM accepted `0x22222222`
- The waiting `0x33333333` input replaced it on the next rising edge

The initial unknown values visible before reset took effect were normal simulation behaviour. The synchronous reset cleared the registers on an active clock edge.

![AXI4-Stream pass-through behavioural simulation](images/phase3-axis-waveform.png)

*Figure 3.2: Behavioural simulation showing normal transfers, backpressure from 50–70 ns, and simultaneous drain and replacement.*
## 3.9 Current Phase 3 status

The completed and remaining work can now be separated clearly.

### 3.9.1 Completed

| Task | Result |
| --- | --- |
| Create Zynq Processing System block design | Complete |
| Add and configure AXI DMA | Complete |
| Establish DMA control and DDR data paths | Complete |
| Generate HDL wrapper | Complete |
| Generate matching `.bit` and `.hwh` files | Complete |
| Resolve PYNQ Python environment issues | Complete |
| Load overlay and identify `axi_dma_0` | Complete |
| Transfer a 32-byte test packet through direct DMA loopback | Passed |
| Design one-word registered AXI4-Stream stage | Complete |
| Implement `TVALID`/`TREADY` backpressure | Complete |
| Propagate `TLAST` | Complete |
| Verify normal transfer in behavioural simulation | Passed |
| Verify simultaneous drain and replacement | Passed |
| Verify output stability under backpressure | Passed |

### 3.9.2 Remaining

The custom RTL has been proven in isolation but has not yet replaced the direct stream loopback in the hardware design.

The remaining integration work is:

1. Add `axis_passthrough.sv` to the Vivado project as a design source.
2. Add the module to the block design using Module Reference.
3. Remove the direct MM2S-to-S2MM AXI4-Stream connection.
4. Connect DMA `M_AXIS_MM2S` to the custom block input.
5. Connect the custom block output to DMA `S_AXIS_S2MM`.
6. Connect `aclk` to the same AXI clock used by the DMA stream interfaces.
7. Connect `aresetn` to the appropriate active-low peripheral reset.
8. Check whether the configured DMA interfaces expose `TKEEP`.
9. Add or tie off `TKEEP` correctly if required.
10. Validate the Vivado block design.
11. Regenerate output products and the HDL wrapper if Vivado requires it.
12. Generate a new bitstream and matching `.hwh`.
13. Copy the new overlay files to the PYNQ.
14. Repeat the Python DMA loopback test through the custom RTL block.
15. Test repeated packets, different transfer lengths, and reset recovery.

## 3.10 Expected integrated design

After the next integration step, the hardware path will become: PS DDR transmit buffer ->DMA MM2S memory-mapped read ->DMA M_AXIS_MM2S ->axis_passthrough S_AXIS -> one-word registered AXI4-Stream stage ->axis_passthrough M_AXIS ->
DMA S_AXIS_S2MM -> DMA S2MM memory-mapped write -> PS DDR receive buffer

The Python validation should still observe exact equality between transmit and receive buffers because the pass-through block intentionally does not alter the data.

The important difference is that the stream will now cross user-written RTL. Once this hardware test passes, the pass-through operation can be extended into packet parsing, validation, filtering, sequence checking, or other HFT-specific processing without changing the surrounding DMA architecture.

## 3.11 Phase 3 acceptance criteria

Phase 3 can be considered complete when all of the following conditions are satisfied:

- The new overlay containing `axis_passthrough` loads successfully
- PYNQ identifies the AXI DMA using the new `.hwh`
- MM2S and S2MM complete without DMA error flags
- Python does not hang while waiting for either DMA channel
- The received array exactly matches the transmitted array
- The final stream word correctly asserts `TLAST`
- Multiple consecutive transfers complete correctly
- Reset returns the custom stream stage to an empty state
- No word is lost, duplicated, reordered, or overwritten
- Optional ILA observation agrees with the expected `TVALID`/`TREADY` behaviour

Once these criteria pass, the PS↔PL AXI communication infrastructure will be established and ready for the actual HFT packet-processing pipeline.
