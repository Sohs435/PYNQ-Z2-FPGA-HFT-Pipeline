
//Defines the complete HFT1 parser interface
//Implements a one-beat registered AXI4-Stream forwarding stage
//Preserves TDATA, TKEEP and TLAST
//Applies backpressure when the output register is occupied

module hft_packet_parser #(
    parameter logic TLAST_PER_PACKET = 1'b1
    
)(
    input  logic         aclk,
    input  logic         aresetn,

    // AXI4-Stream input from AXI DMA MM2S
    input  logic [31:0]  s_axis_tdata,
    input  logic [3:0]   s_axis_tkeep,
    input  logic         s_axis_tvalid,
    output logic         s_axis_tready,
    input  logic         s_axis_tlast,

    // AXI4-Stream output to AXI FIFO / AXI DMA S2MM
    output logic [31:0] m_axis_tdata,
    output logic [3:0] m_axis_tkeep,
    output logic m_axis_tvalid,
    input  logic m_axis_tready,
    output logic m_axis_tlast,

    // Decoded HFT1 fields
    output logic [31:0] magic,
    output logic [7:0] version,
    output logic [7:0] message_type,
    output logic [7:0] side,
    output logic [7:0] reserved_field,
    output logic [31:0] seq,
    output logic [63:0] timestamp_ns,
    output logic [31:0] instrument_id,
    output logic [31:0] price_ticks,
    output logic [31:0] quantity,

    // Packet completion and validation status
    output logic packet_valid,
    output logic packet_error,
    output logic [7:0] error_flags,
    
    output logic [2:0] word_index
);
    // a beat is accepted only when TVALID and TREADY are high
    logic axis_fire;
    
    logic [7:0] current_errors;
    logic [7:0] packet_errors;
    
    localparam logic [7:0] ERROR_MAGIC = 8'b0000_0001;
    localparam logic [7:0] ERROR_VERSION = 8'b0000_0010;
    localparam logic [7:0] ERROR_MESSAGE_TYPE = 8'b0000_0100;
    localparam logic [7:0] ERROR_SIDE = 8'b0000_1000;
    localparam logic [7:0] ERROR_RESERVED = 8'b0001_0000;
    localparam logic [7:0] ERROR_KEEP = 8'b0010_0000;
    localparam logic [7:0] ERROR_EARLY_TLAST = 8'b0100_0000;
    localparam logic [7:0] ERROR_MISSING_TLAST = 8'b1000_0000;
    
    // all this function does is allow for the swapping of byte 
    // order (As LSB and MSB swap ordering see phase 4.1,2 in doc
    // for further info)
    
    function automatic logic [31:0] byte_swap32(
        input logic [31:0] data
    );
        byte_swap32 = {data[7:0], data[15:8], data[23:16], data[31:24]}; 
    
    endfunction 
    
    assign axis_fire = s_axis_tvalid && s_axis_tready;

    // The input may advance when EITHER
    // the output register is empty OR
    // the current output beat is being accepted this cycle.

    // When m_axis_tvalid is high and m_axis_tready is low, this expression
    // becomes zero and backpressure propagates to the upstream DMA.
    always_comb begin
        s_axis_tready = !m_axis_tvalid || m_axis_tready; 
    end
    
    always_comb begin 
    
        current_errors = 8'b0;
        
        // Every beat needs 4 valid bytes = 32 valid bits 
        if (s_axis_tkeep != 4'hF)
            current_errors = current_errors | ERROR_KEEP;
            
        // In single-packet mode, every 32-byte packet must end with TLAST.
        if (TLAST_PER_PACKET) begin
            if ((word_index == 3'd7) && !s_axis_tlast)
                current_errors = current_errors | ERROR_MISSING_TLAST;

            if ((word_index != 3'd7) && s_axis_tlast)
                current_errors = current_errors |ERROR_EARLY_TLAST;
            end
        else begin
            // In batch mode, TLAST occurs only at the end of the complete
            // DMA batch. If TLAST occurs, it must still align with beat 7.
            if ((word_index != 3'd7) && s_axis_tlast)
                current_errors = current_errors | ERROR_EARLY_TLAST;
        end
        
        case (word_index)
            3'd0: begin 
                if(byte_swap32(s_axis_tdata) != 32'h48465431) 
                    current_errors = current_errors | ERROR_MAGIC;
            end 
            
            3'd1: begin 
                if (s_axis_tdata[7:0] != 8'h01)
                    current_errors = current_errors | ERROR_VERSION;
                
                case (s_axis_tdata[15:8])
                8'd1: begin
                    // Quote: side 0 = BID, side 1 = ASK.
                    if ((s_axis_tdata[23:16] != 8'd0) &&
                        (s_axis_tdata[23:16] != 8'd1))
                        current_errors = current_errors | ERROR_SIDE;
                end

                8'd4, 8'd5: begin
                    // STREAM_START and STREAM_END use side 0.
                    if (s_axis_tdata[23:16] != 8'd0)
                        current_errors = current_errors | ERROR_SIDE;
                end

                default: begin
                    current_errors = current_errors |
                                     ERROR_MESSAGE_TYPE;
                end
                endcase

                if (s_axis_tdata[31:24] != 8'h00)
                current_errors = current_errors | ERROR_RESERVED;
                end 
                endcase 
    
          end

    // One-beat elastic output register.
    // If the downstream interface stalls, s_axis_tready becomes low and none
    // of the registered AXI outputs change. This satisfies the AXI4-Stream
    // requirement that data and sideband signals remain stable while
    // TVALID and !TREADY.
    always_ff @(posedge aclk) begin
        if (!aresetn) begin
            m_axis_tdata <= 32'b0;
            m_axis_tkeep <= 4'b0;
            m_axis_tvalid <= 1'b0;
            m_axis_tlast <= 1'b0;

            magic <= 32'b0;
            version <= 8'b0;
            message_type <= 8'b0;
            side <= 8'b0;
            reserved_field <= 8'b0;
            seq <= 32'b0;
            timestamp_ns  <= 64'b0;
            instrument_id <= 32'b0;
            price_ticks <= 32'b0;
            quantity <= 32'b0;
            
            packet_valid <= 1'b0;
            packet_error <= 1'b0;
            error_flags <= 8'b0;
            packet_errors <= 8'b0;
            word_index <= 3'b0; 
            
        end 
        else begin
            // These become one-cycle completion pulses in the validation
            // stage. They remain inactive in the forwarding-only stage.
            packet_valid <= 1'b0;
            packet_error <= 1'b0;
            error_flags <= 8'b0;
            
            // 8 beats as 4 bytes = 32 bits * 8 beats = 32 bytes which is one HFT1 packet 
            if(axis_fire) begin 
                case(word_index)
                    3'd0: begin // This should be the MAGIC part of the packet since it is the most significant
                    // 4 bytes that become the least significant 4 bytes due to the indexing of the addresses
                    // where they are stored
                        magic <= byte_swap32(s_axis_tdata);
                    end
                    
                    3'd1: begin // the version, message type, side, reserved field make up the next 4 bytes
                    // they come in the second beat/burst. No need to perform byte swap we anyways need to assign
                    // a seperate byte to each 
                        version <= s_axis_tdata[7:0];
                        message_type <= s_axis_tdata[15:8];
                        side <= s_axis_tdata [23:16];
                        reserved_field <= s_axis_tdata[31:24]; 
                    end 
                    
                    3'd2: begin //sequence makes up 4 bytes and takes up a full beat
                        seq <= byte_swap32(s_axis_tdata);
                    end 
                    3'd3: begin // The most significant 4 bytes of the timestamp come now due to the reversal of 
                    // byte order
                        timestamp_ns[63:32] <= byte_swap32(s_axis_tdata);
                    end 
                    3'd4: begin
                        timestamp_ns[31:0] <= byte_swap32(s_axis_tdata); 
                    end 
                    3'd5: begin
                        instrument_id <= byte_swap32(s_axis_tdata);
                    end 
                    3'd6: begin 
                        price_ticks <= byte_swap32(s_axis_tdata);
                    end 
                    3'd7: begin
                        quantity <= byte_swap32(s_axis_tdata);
                    end 
                endcase 
                
                if (word_index == 3'd7) begin     
                    word_index <= 3'd0; 
                    error_flags <= packet_errors | current_errors;
                    
                    //No error so packet valid or atleast some error so packet error 
                    if ((packet_errors | current_errors) == 8'b0) packet_valid <= 1'b1;
                    else packet_error <= 1'b1;
                    
                    //clear total errors acrewed before next pack transfer begins 
                    packet_errors <= 8'b0;
                end
                else begin 
                    word_index <= word_index + 3'd1; 
                    packet_errors <= packet_errors | current_errors; 
                end 
            end 

            if (s_axis_tready) begin
                // If no new input beat is available, clear TVALID after the
                // previous output beat has been accepted.
                m_axis_tvalid <= s_axis_tvalid;

                if (s_axis_tvalid) begin
                    m_axis_tdata <= s_axis_tdata;
                    m_axis_tkeep <= s_axis_tkeep;
                    m_axis_tlast <= s_axis_tlast;
                end
            end
        end
    end

endmodule
