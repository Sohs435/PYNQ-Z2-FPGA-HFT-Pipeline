// Verilog wrapper for the SystemVerilog HFT1 packet parser.
//
// The block-design-facing output is named "qntity" because Vivado IP
// Integrator warns about "quantity". The underlying SystemVerilog parser
// can continue using "quantity".

module hft_packet_parser_wrapper (
    // Shared AXI4-Stream clock and active-low reset
    (* X_INTERFACE_INFO = "xilinx.com:signal:clock:1.0 aclk CLK" *)
    (* X_INTERFACE_PARAMETER = "XIL_INTERFACENAME aclk, ASSOCIATED_BUSIF S_AXIS:M_AXIS, ASSOCIATED_RESET aresetn" *)
    input  wire         aclk,

    (* X_INTERFACE_INFO = "xilinx.com:signal:reset:1.0 aresetn RST" *)
    (* X_INTERFACE_PARAMETER = "XIL_INTERFACENAME aresetn, POLARITY ACTIVE_LOW" *)
    input  wire         aresetn,

    // AXI4-Stream slave input from AXI DMA MM2S
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 S_AXIS TDATA" *)
    input  wire [31:0]  s_axis_tdata,

    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 S_AXIS TKEEP" *)
    input  wire [3:0]   s_axis_tkeep,

    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 S_AXIS TVALID" *)
    input  wire         s_axis_tvalid,

    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 S_AXIS TREADY" *)
    output wire         s_axis_tready,

    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 S_AXIS TLAST" *)
    input  wire         s_axis_tlast,

    // AXI4-Stream master output to AXI Stream FIFO
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 M_AXIS TDATA" *)
    output wire [31:0]  m_axis_tdata,

    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 M_AXIS TKEEP" *)
    output wire [3:0]   m_axis_tkeep,

    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 M_AXIS TVALID" *)
    output wire         m_axis_tvalid,

    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 M_AXIS TREADY" *)
    input  wire         m_axis_tready,

    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 M_AXIS TLAST" *)
    output wire         m_axis_tlast,

    // Decoded HFT1 fields
    output wire [31:0]  magic,
    output wire [7:0]   version,
    output wire [7:0]   message_type,
    output wire [7:0]   side,
    output wire [7:0]   reserved_field,
    output wire [31:0]  seq,
    output wire [63:0]  timestamp_ns,
    output wire [31:0]  instrument_id,
    output wire [31:0]  price_ticks,

    // Wrapper-facing alias for the parser's "quantity" output
    output wire [31:0]  qntity,

    // Packet position and validation status
    output wire [2:0]   word_index,
    output wire         packet_valid,
    output wire         packet_error,
    output wire [7:0]   error_flags
);

    hft_packet_parser #(
        .TLAST_PER_PACKET (1'b0)
    ) parser_i (
        // Parser port mappings
        .aclk           (aclk),
        .aresetn        (aresetn),

        .s_axis_tdata   (s_axis_tdata),
        .s_axis_tkeep   (s_axis_tkeep),
        .s_axis_tvalid  (s_axis_tvalid),
        .s_axis_tready  (s_axis_tready),
        .s_axis_tlast   (s_axis_tlast),

        .m_axis_tdata   (m_axis_tdata),
        .m_axis_tkeep   (m_axis_tkeep),
        .m_axis_tvalid  (m_axis_tvalid),
        .m_axis_tready  (m_axis_tready),
        .m_axis_tlast   (m_axis_tlast),

        .magic          (magic),
        .version        (version),
        .message_type   (message_type),
        .side           (side),
        .reserved_field (reserved_field),
        .seq            (seq),
        .timestamp_ns   (timestamp_ns),
        .instrument_id  (instrument_id),
        .price_ticks    (price_ticks),

        // Parser port -> wrapper output
        .quantity       (qntity),

        .word_index     (word_index),
        .packet_valid   (packet_valid),
        .packet_error   (packet_error),
        .error_flags    (error_flags)
    );

endmodule
