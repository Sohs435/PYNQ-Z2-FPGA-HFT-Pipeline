module hft_sequence_tracker (
    input logic clk,
    input logic resetn,

    input logic stream_start_pulse,
    input logic stream_end_pulse,

    input logic quote_valid,
    input logic [2:0] instrument_slot,
    input logic [7:0] quote_side,
    input logic [31:0] quote_seq,
    input logic [63:0] quote_timestamp_ns,
    input logic [31:0] quote_price_ticks,
    input logic [31:0] quote_quantity,

    output logic tracked_quote_valid,
    output logic [2:0] tracked_instrument_slot,
    output logic [7:0] tracked_side,
    output logic [31:0] tracked_seq,
    output logic [63:0] tracked_timestamp_ns,
    output logic [31:0] tracked_price_ticks,
    output logic [31:0] tracked_quantity,

    output logic sequence_initialized,
    output logic sequence_error,
    output logic missing_packet,
    output logic duplicate_packet,
    output logic out_of_order_packet,

    output logic [31:0] expected_seq,
    output logic [31:0] missing_count,
    output logic [31:0] duplicate_count,
    output logic [31:0] out_of_order_count
);

    logic [31:0] last_seq;

    always_ff @(posedge clk) begin
        if (!resetn) begin
            last_seq <= '0;
            expected_seq <= '0;
            sequence_initialized <= 1'b0;

            sequence_error <= 1'b0;
            missing_packet <= 1'b0;
            duplicate_packet <= 1'b0;
            out_of_order_packet <= 1'b0;

            missing_count <= '0;
            duplicate_count <= '0;
            out_of_order_count <= '0;

            tracked_quote_valid <= 1'b0;
            tracked_instrument_slot <= '0;
            tracked_side <= '0;
            tracked_seq <= '0;
            tracked_timestamp_ns <= '0;
            tracked_price_ticks <= '0;
            tracked_quantity <= '0;
        end
        else begin
            tracked_quote_valid <= 1'b0;
            sequence_error <= 1'b0;
            missing_packet <= 1'b0;
            duplicate_packet <= 1'b0;
            out_of_order_packet <= 1'b0;

            if (stream_start_pulse) begin
                last_seq <= '0;
                expected_seq <= '0;
                sequence_initialized <= 1'b0;

                missing_count <= '0;
                duplicate_count <= '0;
                out_of_order_count <= '0;
            end
            else if (stream_end_pulse) begin
                sequence_initialized <= 1'b0;
            end
            else if (quote_valid) begin
                if (!sequence_initialized) begin
                    last_seq <= quote_seq;
                    expected_seq <= quote_seq + 32'd1;
                    sequence_initialized <= 1'b1;

                    tracked_quote_valid <= 1'b1;
                    tracked_instrument_slot <= instrument_slot;
                    tracked_side <= quote_side;
                    tracked_seq <= quote_seq;
                    tracked_timestamp_ns <= quote_timestamp_ns;
                    tracked_price_ticks <= quote_price_ticks;
                    tracked_quantity <= quote_quantity;
                end
                else if (quote_seq == expected_seq) begin
                    last_seq <= quote_seq;
                    expected_seq <= quote_seq + 32'd1;

                    tracked_quote_valid <= 1'b1;
                    tracked_instrument_slot <= instrument_slot;
                    tracked_side <= quote_side;
                    tracked_seq <= quote_seq;
                    tracked_timestamp_ns <= quote_timestamp_ns;
                    tracked_price_ticks <= quote_price_ticks;
                    tracked_quantity <= quote_quantity;
                end
                else if (quote_seq == last_seq) begin
                    duplicate_packet <= 1'b1;
                    sequence_error <= 1'b1;
                    duplicate_count <= duplicate_count + 32'd1;
                end
                else if (quote_seq > expected_seq) begin
                    missing_packet <= 1'b1;
                    sequence_error <= 1'b1;

                    missing_count <= missing_count
                        + (quote_seq - expected_seq);

                    last_seq <= quote_seq;
                    expected_seq <= quote_seq + 32'd1;

                    tracked_quote_valid <= 1'b1;
                    tracked_instrument_slot <= instrument_slot;
                    tracked_side <= quote_side;
                    tracked_seq <= quote_seq;
                    tracked_timestamp_ns <= quote_timestamp_ns;
                    tracked_price_ticks <= quote_price_ticks;
                    tracked_quantity <= quote_quantity;
                end
                else begin
                    out_of_order_packet <= 1'b1;
                    sequence_error <= 1'b1;
                    out_of_order_count <= out_of_order_count + 32'd1;
                end
            end
        end
    end

endmodule
