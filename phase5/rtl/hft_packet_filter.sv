module hft_packet_filter #(
    parameter logic [31:0] INSTRUMENT_ID_0 = 32'd1,
    parameter logic [31:0] INSTRUMENT_ID_1 = 32'd2,
    parameter logic [31:0] INSTRUMENT_ID_2 = 32'd3,
    parameter logic [31:0] INSTRUMENT_ID_3 = 32'd4,
    parameter logic [31:0] INSTRUMENT_ID_4 = 32'd5 // 5 companies only for now 
)(
    input logic clk,
    input logic resetn, 
    
    input logic packet_valid, 
    input logic packet_error, 
    input logic [7:0] message_type, 
    input logic [7:0] side,
    input logic [31:0] seq, 
    input logic [63:0] timestamp_ns, 
    input logic [31:0] instrument_id, 
    input logic [31:0] price_ticks, 
    input logic [31:0] qntity,
    
    output logic quote_valid,
    output logic [2:0] instrument_slot, 
    output logic [7:0]  quote_side,
    output logic [31:0] quote_seq,
    output logic [63:0] quote_timestamp_ns,
    output logic [31:0] quote_price_ticks,
    output logic [31:0] quote_quantity,

    output logic stream_active,
    output logic stream_start_pulse,
    output logic stream_end_pulse,
    output logic unknown_instrument
);
    localparam logic [7:0] MESSAGE_QUOTE_UPDATE = 8'd1;
    localparam logic [7:0] MESSAGE_STREAM_START = 8'd4;
    localparam logic [7:0] MESSAGE_STREAM_END = 8'd5;

    logic instrument_found;
    logic [2:0] matched_slot;
    
    always_comb begin
        instrument_found = 1'b1; //default scenario will change it 
        // to 0 when necessary 
        matched_slot     = 3'd0;

        case (instrument_id)
            INSTRUMENT_ID_0: matched_slot = 3'd0;
            INSTRUMENT_ID_1: matched_slot = 3'd1;
            INSTRUMENT_ID_2: matched_slot = 3'd2;
            INSTRUMENT_ID_3: matched_slot = 3'd3;
            INSTRUMENT_ID_4: matched_slot = 3'd4;

            default: begin
                instrument_found = 1'b0;
                matched_slot = 3'd0;
            end
        endcase
    end
    
    always_ff @(posedge clk) begin
        if (!resetn) begin
            quote_valid <= 1'b0;
            instrument_slot <= '0;
            quote_side <= '0;
            quote_seq <= '0;
            quote_timestamp_ns <= '0;
            quote_price_ticks <= '0;
            quote_quantity <= '0;

            stream_active <= 1'b0;
            stream_start_pulse <= 1'b0;
            stream_end_pulse <= 1'b0;
            unknown_instrument <= 1'b0;
        end
        else begin 
            quote_valid <= 1'b0; 
            stream_start_pulse <= 1'b0;
            stream_end_pulse <= 1'b0;
            unknown_instrument <= 1'b0; 
            
            if (packet_valid && !packet_error) begin
                if (message_type == MESSAGE_STREAM_START) begin 
                    stream_active <= 1'b1;
                    stream_start_pulse <= 1'b1; 
                end 
                
                else if (message_type == MESSAGE_STREAM_END) begin 
                    stream_active <= 1'b0; 
                    stream_end_pulse <= 1'b1; 
                end 
                
                else if (
                    message_type == MESSAGE_QUOTE_UPDATE &&
                    stream_active
                ) begin
                
                    if (instrument_found) begin
                        quote_valid <= 1'b1;
                        instrument_slot <= matched_slot;
                        quote_side <= side;
                        quote_seq <= seq;
                        quote_timestamp_ns <= timestamp_ns;
                        quote_price_ticks <= price_ticks;
                        quote_quantity <= qntity;
                    end
                    
                    else unknown_instrument <= 1'b1; 
                    
                end 
            end 
        end 
    end 
endmodule 
