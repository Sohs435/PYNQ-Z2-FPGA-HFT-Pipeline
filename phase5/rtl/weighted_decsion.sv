`timescale 1ns / 1ps

module weighted_decision#(
    parameter logic signed [15:0] TREND_WEIGHT = 16'sd4,
    parameter logic signed [15:0] IMBALANCE_WEIGHT = 16'sd1,
    parameter logic [15:0] SPREAD_WEIGHT = 16'd2,
    parameter logic signed [63:0] BASE_THRESHOLD = 64'sd100

)(
    input logic clk, 
    input logic resetn,
    
    input logic feature_valid,
    input logic [2:0] instrument_slot, 
    input logic [63:0] feature_timestamp_ns,
    
    input logic signed [33:0] trend,
    input logic signed [32:0] quantity_imbalance,
    input logic [31:0] spread,
    
    output logic signal_valid,
    output logic [2:0] signal_instrument_slot,
    output logic [63:0] signal_timestamp_ns,

    output logic [1:0] trade_signal,
    output logic signed [63:0] direction_score,
    output logic signed [63:0] required_score
    
    
    );
    
    // Pipeline registers
    logic signed [63:0] trend_product_s1;
    logic signed [63:0] imbalance_product_s1;
    logic signed [63:0] spread_product_s1;

    logic               valid_s1;
    logic [2:0]         instrument_slot_s1;
    logic [63:0]        timestamp_s1;

    logic signed [63:0] direction_score_s2;
    logic signed [63:0] required_score_s2;

    logic               valid_s2;
    logic [2:0]         instrument_slot_s2;
    logic [63:0]        timestamp_s2;
    
    localparam logic [1:0] SIGNAL_HOLD = 2'b00;
    localparam logic [1:0] SIGNAL_BUY  = 2'b01;
    localparam logic [1:0] SIGNAL_SELL = 2'b10;

    always_ff @(posedge clk) begin
        if (!resetn) begin
            // Stage 1
            trend_product_s1 <= '0;
            imbalance_product_s1 <= '0;
            spread_product_s1 <= '0;
            valid_s1 <= 1'b0;
            instrument_slot_s1 <= '0;
            timestamp_s1 <= '0;

            // Stage 2
            direction_score_s2 <= '0;
            required_score_s2 <= '0;
            valid_s2 <= 1'b0;
            instrument_slot_s2 <= '0;
            timestamp_s2 <= '0;

            // Stage 3
            signal_valid <= 1'b0;
            signal_instrument_slot <= '0;
            signal_timestamp_ns <= '0;
            trade_signal <= SIGNAL_HOLD;
            direction_score <= '0;
            required_score <= '0;
        end
        else begin
            // Stage 1: weighted multiplications
            trend_product_s1 <= $signed(trend) * $signed(TREND_WEIGHT);

            imbalance_product_s1 <= $signed(quantity_imbalance)*$signed(IMBALANCE_WEIGHT);

            spread_product_s1 <= $signed({1'b0, spread}) * $signed({1'b0, SPREAD_WEIGHT});

            valid_s1 <= feature_valid;
            instrument_slot_s1 <= instrument_slot;
            timestamp_s1       <= feature_timestamp_ns;

            // Stage 2: score and threshold calculation
            direction_score_s2 <= trend_product_s1 + imbalance_product_s1;

            required_score_s2 <= BASE_THRESHOLD + spread_product_s1;

            valid_s2 <= valid_s1;
            instrument_slot_s2 <= instrument_slot_s1;
            timestamp_s2 <= timestamp_s1;

            // Stage 3: register scores and metadata
            signal_valid <= valid_s2;
            signal_instrument_slot <= instrument_slot_s2;
            signal_timestamp_ns <= timestamp_s2;
            direction_score <= direction_score_s2;
            required_score <= required_score_s2;

            // Stage 3: BUY/SELL/HOLD comparison
            if (valid_s2) begin
                if (direction_score_s2 > required_score_s2) begin
                    trade_signal <= SIGNAL_BUY;
                end
                else if (direction_score_s2 < -required_score_s2) begin
                    trade_signal <= SIGNAL_SELL;
                end
                else begin
                    trade_signal <= SIGNAL_HOLD;
                end
            end
            else begin
                trade_signal <= SIGNAL_HOLD;
            end
        end
    end
endmodule
