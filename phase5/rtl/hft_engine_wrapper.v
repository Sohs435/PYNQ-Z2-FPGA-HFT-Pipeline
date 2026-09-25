`timescale 1ns / 1ps

module hft_engine_wrapper #(
    parameter [31:0] INSTRUMENT_ID_0 = 32'd1,
    parameter [31:0] INSTRUMENT_ID_1 = 32'd2,
    parameter [31:0] INSTRUMENT_ID_2 = 32'd3,
    parameter [31:0] INSTRUMENT_ID_3 = 32'd4,
    parameter [31:0] INSTRUMENT_ID_4 = 32'd5,

    parameter integer TREND_WEIGHT = 4,
    parameter integer IMBALANCE_WEIGHT = 1,
    parameter integer SPREAD_WEIGHT = 2,
    parameter integer BASE_THRESHOLD = 100
)(
    input wire clk,
    input wire resetn,

    // Parsed packet inputs from the Phase 4 packet parser
    input wire packet_valid,
    input wire packet_error,
    input wire [7:0] message_type,
    input wire [7:0] side,
    input wire [31:0] seq,
    input wire [63:0] timestamp_ns,
    input wire [31:0] instrument_id,
    input wire [31:0] price_ticks,
    input wire [31:0] qntity,

    // Final trading-decision outputs
    output wire signal_valid,
    output wire [2:0] signal_instrument_slot,
    output wire [63:0] signal_timestamp_ns,
    output wire [1:0] trade_signal,
    output wire signed [63:0] direction_score,
    output wire signed [63:0] required_score
);

    // The packet filter produces accepted quote updates.
    // It also controls the active market-data stream.
    // Instrument IDs are converted into internal slots.
    wire quote_valid;
    wire [2:0] quote_instrument_slot;
    wire [7:0] quote_side;
    wire [31:0] quote_seq;
    wire [63:0] quote_timestamp_ns;
    wire [31:0] quote_price_ticks;
    wire [31:0] quote_quantity;

    wire stream_active;
    wire stream_start_pulse;
    wire stream_end_pulse;
    wire unknown_instrument;

    // The sequence tracker forwards only acceptable sequences.
    // Missing packets are counted and accepted with resynchronisation.
    // Duplicate and out-of-order packets are rejected.
    wire tracked_quote_valid;
    wire [2:0] tracked_instrument_slot;
    wire [7:0] tracked_side;
    wire [31:0] tracked_seq;
    wire [63:0] tracked_timestamp_ns;
    wire [31:0] tracked_price_ticks;
    wire [31:0] tracked_quantity;

    wire sequence_initialized;
    wire sequence_error;
    wire missing_packet;
    wire duplicate_packet;
    wire out_of_order_packet;

    wire [31:0] expected_seq;
    wire [31:0] missing_count;
    wire [31:0] duplicate_count;
    wire [31:0] out_of_order_count;

    // The instrument book stores bid and ask values per slot.
    // Each accepted quote produces an updated book snapshot.
    // book_valid indicates that both sides have been initialized.
    wire book_update_valid;
    wire [2:0] book_instrument_slot;
    wire [31:0] book_seq;   
    wire [63:0] book_timestamp_ns;

    wire [31:0] book_bid_price;
    wire [31:0] book_bid_quantity;
    wire [31:0] book_ask_price;
    wire [31:0] book_ask_quantity;

    wire book_valid;
    wire crossed_book;

    // The feature engine produces the three decision features.
    // Every instrument owns independent moving-average state.
    // Features become valid after the 32-sample warm-up.
    wire feature_valid;
    wire [2:0] feature_instrument_slot;
    wire [63:0] feature_timestamp_ns;

    wire signed [33:0] trend;
    wire signed [32:0] quantity_imbalance;
    wire [31:0] spread;

    // Phase 5.2 filters packets and maps instrument IDs.
    // Quotes are accepted only while the stream is active.
    // Invalid packets and unsupported instruments are rejected.
    hft_packet_filter #(
        .INSTRUMENT_ID_0(INSTRUMENT_ID_0),
        .INSTRUMENT_ID_1(INSTRUMENT_ID_1),
        .INSTRUMENT_ID_2(INSTRUMENT_ID_2),
        .INSTRUMENT_ID_3(INSTRUMENT_ID_3),
        .INSTRUMENT_ID_4(INSTRUMENT_ID_4)
    ) packet_filter_inst (
        .clk(clk),
        .resetn(resetn),

        .packet_valid(packet_valid),
        .packet_error(packet_error),
        .message_type(message_type),
        .side(side),
        .seq(seq),
        .timestamp_ns(timestamp_ns),
        .instrument_id(instrument_id),
        .price_ticks(price_ticks),
        .qntity(qntity),

        .quote_valid(quote_valid),
        .instrument_slot(quote_instrument_slot),
        .quote_side(quote_side),
        .quote_seq(quote_seq),
        .quote_timestamp_ns(quote_timestamp_ns),
        .quote_price_ticks(quote_price_ticks),
        .quote_quantity(quote_quantity),

        .stream_active(stream_active),
        .stream_start_pulse(stream_start_pulse),
        .stream_end_pulse(stream_end_pulse),
        .unknown_instrument(unknown_instrument)
    );

    // Phase 5.3 verifies the global quote sequence.
    // Accepted quotes continue to the instrument books.
    // Sequence errors are retained as internal diagnostics.
    hft_sequence_tracker sequence_tracker_inst (
        .clk(clk),
        .resetn(resetn),

        .stream_start_pulse(stream_start_pulse),
        .stream_end_pulse(stream_end_pulse),

        .quote_valid(quote_valid),
        .instrument_slot(quote_instrument_slot),
        .quote_side(quote_side),
        .quote_seq(quote_seq),
        .quote_timestamp_ns(quote_timestamp_ns),
        .quote_price_ticks(quote_price_ticks),
        .quote_quantity(quote_quantity),

        .tracked_quote_valid(tracked_quote_valid),
        .tracked_instrument_slot(tracked_instrument_slot),
        .tracked_side(tracked_side),
        .tracked_seq(tracked_seq),
        .tracked_timestamp_ns(tracked_timestamp_ns),
        .tracked_price_ticks(tracked_price_ticks),
        .tracked_quantity(tracked_quantity),

        .sequence_initialized(sequence_initialized),
        .sequence_error(sequence_error),
        .missing_packet(missing_packet),
        .duplicate_packet(duplicate_packet),
        .out_of_order_packet(out_of_order_packet),

        .expected_seq(expected_seq),
        .missing_count(missing_count),
        .duplicate_count(duplicate_count),
        .out_of_order_count(out_of_order_count)
    );

    // Phase 5.4 maintains the bid and ask for each instrument.
    // An updated complete book is forwarded to the feature engine.
    // Crossed books are marked so that they can be rejected.
    hft_instrument_book instrument_book_inst (
        .clk(clk),
        .resetn(resetn),

        .stream_start_pulse(stream_start_pulse),
        .stream_end_pulse(stream_end_pulse),

        .tracked_quote_valid(tracked_quote_valid),
        .tracked_instrument_slot(tracked_instrument_slot),
        .tracked_side(tracked_side),
        .tracked_seq(tracked_seq),
        .tracked_timestamp_ns(tracked_timestamp_ns),
        .tracked_price_ticks(tracked_price_ticks),
        .tracked_quantity(tracked_quantity),

        .book_update_valid(book_update_valid),
        .book_instrument_slot(book_instrument_slot),
        .book_seq(book_seq),
        .book_timestamp_ns(book_timestamp_ns),

        .book_bid_price(book_bid_price),
        .book_bid_quantity(book_bid_quantity),
        .book_ask_price(book_ask_price),
        .book_ask_quantity(book_ask_quantity),

        .book_valid(book_valid),
        .crossed_book(crossed_book)
    );

    // Phase 5.5 calculates trend, imbalance and spread.
    // Incomplete and crossed books do not update the histories.
    // Eligible updates are processed as soon as they arrive.
    hft_feature_engine feature_engine_inst (
        .clk(clk),
        .resetn(resetn),

        .stream_start_pulse(stream_start_pulse),
        .stream_end_pulse(stream_end_pulse),

        .book_update_valid(book_update_valid),
        .book_instrument_slot(book_instrument_slot),
        .book_timestamp_ns(book_timestamp_ns),

        .book_bid_price(book_bid_price),
        .book_bid_quantity(book_bid_quantity),
        .book_ask_price(book_ask_price),
        .book_ask_quantity(book_ask_quantity),

        .book_valid(book_valid),
        .crossed_book(crossed_book),

        .feature_valid(feature_valid),
        .feature_instrument_slot(feature_instrument_slot),
        .feature_timestamp_ns(feature_timestamp_ns),

        .trend(trend),
        .quantity_imbalance(quantity_imbalance),
        .spread(spread)
    );

    // Phase 5.1 applies the configurable feature weights.
    // The weighted score is compared against the spread threshold.
    // The registered result is BUY, SELL or HOLD.
   weighted_decision #(
    .TREND_WEIGHT(16'sd4),
    .IMBALANCE_WEIGHT(16'sd1),
    .SPREAD_WEIGHT(16'd2),
    .BASE_THRESHOLD(64'sd100)
    ) weighted_decision_inst (
        .clk(clk),
        .resetn(resetn),

        .feature_valid(feature_valid),
        .instrument_slot(feature_instrument_slot),
        .feature_timestamp_ns(feature_timestamp_ns),

        .trend(trend),
        .quantity_imbalance(quantity_imbalance),
        .spread(spread),

        .signal_valid(signal_valid),
        .signal_instrument_slot(signal_instrument_slot),
        .signal_timestamp_ns(signal_timestamp_ns),

        .trade_signal(trade_signal),
        .direction_score(direction_score),
        .required_score(required_score)
    );

endmodule
