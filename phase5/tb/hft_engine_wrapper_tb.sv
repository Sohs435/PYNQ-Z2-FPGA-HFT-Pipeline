`timescale 1ns / 1ps

module hft_engine_wrapper_tb;

    localparam logic [7:0] MESSAGE_QUOTE_UPDATE = 8'd1;
    localparam logic [7:0] MESSAGE_STREAM_START = 8'd4;
    localparam logic [7:0] MESSAGE_STREAM_END = 8'd5;

    localparam logic [7:0] SIDE_BID = 8'd0;
    localparam logic [7:0] SIDE_ASK = 8'd1;

    localparam logic [1:0] SIGNAL_HOLD = 2'b00;
    localparam logic [1:0] SIGNAL_BUY = 2'b01;
    localparam logic [1:0] SIGNAL_SELL = 2'b10;

    logic clk;
    logic resetn;

    logic packet_valid;
    logic packet_error;
    logic [7:0] message_type;
    logic [7:0] side;
    logic [31:0] seq;
    logic [63:0] timestamp_ns;
    logic [31:0] instrument_id;
    logic [31:0] price_ticks;
    logic [31:0] qntity;

    wire signal_valid;
    wire [2:0] signal_instrument_slot;
    wire [63:0] signal_timestamp_ns;
    wire [1:0] trade_signal;
    wire signed [63:0] direction_score;
    wire signed [63:0] required_score;

    integer errors;
    integer sample_index;
    integer timeout_count;
    integer signal_count;

    hft_engine_wrapper dut (
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

        .signal_valid(signal_valid),
        .signal_instrument_slot(signal_instrument_slot),
        .signal_timestamp_ns(signal_timestamp_ns),
        .trade_signal(trade_signal),
        .direction_score(direction_score),
        .required_score(required_score)
    );

    // Generate a 100 MHz simulation clock.
    // Each complete clock period is ten nanoseconds.
    // Every module in the wrapper uses this clock.
    initial begin
        clk = 1'b0;

        forever begin
            #5 clk = ~clk;
        end
    end

    // Count every valid trading signal.
    // This detects unexpected decisions during warm-up.
    // Reset clears the observed signal count.
    always @(posedge clk) begin
        if (!resetn) begin
            signal_count = 0;
        end
        else if (signal_valid) begin
            signal_count = signal_count + 1;
        end
    end

    // Check one Boolean test condition.
    // A true condition produces a PASS message.
    // A false or unknown condition increments errors.
    task automatic check_condition(
        input logic condition,
        input string test_name
    );
        begin
            if (condition === 1'b1) begin
                $display("PASS: %s", test_name);
            end
            else begin
                $error("FAIL: %s", test_name);
                errors = errors + 1;
            end
        end
    endtask

    // Apply one decoded parser result to the wrapper.
    // The packet is held valid across one rising edge.
    // Inputs only change on falling clock edges.
    task automatic send_packet(
        input logic error_value,
        input logic [7:0] type_value,
        input logic [7:0] side_value,
        input logic [31:0] sequence_value,
        input logic [63:0] timestamp_value,
        input logic [31:0] instrument_value,
        input logic [31:0] price_value,
        input logic [31:0] quantity_value
    );
        begin
            @(negedge clk);

            packet_valid = 1'b1;
            packet_error = error_value;
            message_type = type_value;
            side = side_value;
            seq = sequence_value;
            timestamp_ns = timestamp_value;
            instrument_id = instrument_value;
            price_ticks = price_value;
            qntity = quantity_value;

            @(posedge clk);
            #1;

            @(negedge clk);

            packet_valid = 1'b0;
            packet_error = 1'b0;
        end
    endtask

    // Wait while asserting that no signal is produced.
    // This checks packet rejection and feature warm-up.
    // Any signal during the interval is a test failure.
    task automatic expect_no_signal(
        input integer cycles,
        input string test_name
    );
        integer cycle_index;
        logic unexpected_signal;

        begin
            unexpected_signal = 1'b0;

            for (
                cycle_index = 0;
                cycle_index < cycles;
                cycle_index = cycle_index + 1
            ) begin
                @(posedge clk);
                #1;

                if (signal_valid === 1'b1) begin
                    unexpected_signal = 1'b1;

                    $error(
                        "FAIL: %s produced signal=%0b slot=%0d timestamp=%0d",
                        test_name,
                        trade_signal,
                        signal_instrument_slot,
                        signal_timestamp_ns
                    );
                end
            end

            if (unexpected_signal) begin
                errors = errors + 1;
            end
            else begin
                $display("PASS: %s", test_name);
            end
        end
    endtask

    // Wait for one trading signal with a timeout.
    // Check the signal, score, threshold and metadata.
    // The timeout prevents the simulation from hanging.
    task automatic expect_signal(
        input logic [2:0] expected_slot,
        input logic [63:0] expected_timestamp,
        input logic [1:0] expected_signal,
        input logic signed [63:0] expected_score,
        input logic signed [63:0] expected_threshold,
        input string test_name
    );
        begin
            timeout_count = 0;

            while (
                signal_valid !== 1'b1 &&
                timeout_count < 40
            ) begin
                @(posedge clk);
                #1;

                timeout_count = timeout_count + 1;
            end

            if (signal_valid !== 1'b1) begin
                $error("FAIL: %s timed out", test_name);
                errors = errors + 1;
            end
            else if (
                signal_instrument_slot !== expected_slot ||
                signal_timestamp_ns !== expected_timestamp ||
                trade_signal !== expected_signal ||
                direction_score !== expected_score ||
                required_score !== expected_threshold
            ) begin
                $error(
                    "FAIL: %s slot=%0d timestamp=%0d signal=%0b score=%0d threshold=%0d",
                    test_name,
                    signal_instrument_slot,
                    signal_timestamp_ns,
                    trade_signal,
                    $signed(direction_score),
                    $signed(required_score)
                );

                errors = errors + 1;
            end
            else begin
                $display(
                    "PASS: %s slot=%0d timestamp=%0d signal=%0b score=%0d threshold=%0d",
                    test_name,
                    signal_instrument_slot,
                    signal_timestamp_ns,
                    trade_signal,
                    $signed(direction_score),
                    $signed(required_score)
                );
            end
        end
    endtask

    initial begin
        errors = 0;
        signal_count = 0;

        resetn = 1'b0;

        packet_valid = 1'b0;
        packet_error = 1'b0;
        message_type = '0;
        side = '0;
        seq = '0;
        timestamp_ns = '0;
        instrument_id = '0;
        price_ticks = '0;
        qntity = '0;

        // Test stage 1 asserts reset for three clocks.
        // Final outputs and internal stream state must clear.
        // No trading signal may be marked valid.
        repeat (3) begin
            @(posedge clk);
        end

        #1;

        check_condition(
            signal_valid == 1'b0 &&
            signal_instrument_slot == 3'd0 &&
            signal_timestamp_ns == 64'd0 &&
            trade_signal == SIGNAL_HOLD &&
            direction_score == 64'sd0 &&
            required_score == 64'sd0,
            "reset outputs"
        );

        @(negedge clk);
        resetn = 1'b1;

        // Test stage 2 sends a quote before STREAM_START.
        // The packet filter must reject the quote.
        // No downstream module should initialize.
        send_packet(
            1'b0,
            MESSAGE_QUOTE_UPDATE,
            SIDE_BID,
            32'd1,
            64'd100,
            32'd1,
            32'd1000,
            32'd100
        );

        expect_no_signal(
            8,
            "quote before STREAM_START ignored"
        );

        check_condition(
            dut.stream_active == 1'b0 &&
            dut.sequence_initialized == 1'b0,
            "pipeline remained inactive"
        );

        // Test stage 3 starts the first data stream.
        // The filter must set stream_active.
        // Downstream state must begin from reset values.
        send_packet(
            1'b0,
            MESSAGE_STREAM_START,
            SIDE_BID,
            32'd0,
            64'd200,
            32'd0,
            32'd0,
            32'd0
        );

        expect_no_signal(
            5,
            "STREAM_START produced no trading signal"
        );

        check_condition(
            dut.stream_active == 1'b1,
            "STREAM_START activated pipeline"
        );

        // Test stage 4 sends erroneous and unknown packets.
        // Neither packet may initialize sequence tracking.
        // Neither packet may modify an instrument book.
        send_packet(
            1'b1,
            MESSAGE_QUOTE_UPDATE,
            SIDE_BID,
            32'd100,
            64'd300,
            32'd1,
            32'd1000,
            32'd100
        );

        send_packet(
            1'b0,
            MESSAGE_QUOTE_UPDATE,
            SIDE_BID,
            32'd100,
            64'd400,
            32'd99,
            32'd1000,
            32'd100
        );

        expect_no_signal(
            8,
            "erroneous and unknown packets rejected"
        );

        check_condition(
            dut.sequence_initialized == 1'b0,
            "rejected packets did not initialize sequence"
        );

        // Test stage 5 constructs a crossed book.
        // A single bid leaves the book incomplete.
        // The crossed complete book must not enter feature history.
        send_packet(
            1'b0,
            MESSAGE_QUOTE_UPDATE,
            SIDE_BID,
            32'd100,
            64'd500,
            32'd1,
            32'd1003,
            32'd100
        );

        send_packet(
            1'b0,
            MESSAGE_QUOTE_UPDATE,
            SIDE_ASK,
            32'd101,
            64'd600,
            32'd1,
            32'd1002,
            32'd100
        );

        expect_no_signal(
            10,
            "crossed book rejected"
        );

        check_condition(
            dut.feature_engine_inst.sample_count[0] == 6'd0,
            "crossed book did not advance feature warm-up"
        );

        // Test stage 6 restarts after the crossed-book test.
        // Sequence, book and feature state must clear.
        // The next quote establishes a fresh sequence.
        send_packet(
            1'b0,
            MESSAGE_STREAM_START,
            SIDE_BID,
            32'd0,
            64'd700,
            32'd0,
            32'd0,
            32'd0
        );

        expect_no_signal(
            6,
            "second STREAM_START cleared pipeline"
        );

        check_condition(
            dut.sequence_initialized == 1'b0 &&
            dut.feature_engine_inst.sample_count[0] == 6'd0 &&
            dut.feature_engine_inst.current_state[0] == 2'd0,
            "fresh stream state"
        );

        // Test stage 7 initializes slot zero's order book.
        // The first bid is incomplete and produces no sample.
        // The first ask creates feature sample number one.
        send_packet(
            1'b0,
            MESSAGE_QUOTE_UPDATE,
            SIDE_BID,
            32'd200,
            64'd10000,
            32'd1,
            32'd1000,
            32'd100
        );

        send_packet(
            1'b0,
            MESSAGE_QUOTE_UPDATE,
            SIDE_ASK,
            32'd201,
            64'd10100,
            32'd1,
            32'd1002,
            32'd100
        );

        // Test stage 8 supplies samples two through 32.
        // Constant midpoint and equal quantities produce zero score.
        // No trading signal is valid before warm-up finishes.
        for (
            sample_index = 2;
            sample_index <= 32;
            sample_index = sample_index + 1
        ) begin
            send_packet(
                1'b0,
                MESSAGE_QUOTE_UPDATE,
                SIDE_BID,
                200 + sample_index,
                10000 + (sample_index * 100),
                32'd1,
                32'd1000,
                32'd100
            );
        end

        // Allow the final quote to propagate through the wrapper.
        // It passes through the filter, tracker and instrument book.
        // The feature engine then registers sample number 32.
        repeat (4) begin
            @(posedge clk);
            #1;
        end

        check_condition(
            dut.feature_engine_inst.sample_count[0] == 6'd32 &&
            dut.feature_engine_inst.current_state[0] == 2'd2,
            "slot 0 completed feature warm-up"
        );

        check_condition(
            signal_count == 0,
            "no signal produced before warm-up completed"
        );

        // Test stage 9 checks the first complete decision.
        // Zero trend and imbalance give direction score zero.
        // Spread two produces required score 104.
        expect_signal(
            3'd0,
            64'd13200,
            SIGNAL_HOLD,
            64'sd0,
            64'sd104,
            "first integrated HOLD"
        );

        // Test stage 10 begins warming a second instrument.
        // Slot one retains independent moving-average state.
        // Slot zero must remain in FEATURE_READY.
        send_packet(
            1'b0,
            MESSAGE_QUOTE_UPDATE,
            SIDE_BID,
            32'd233,
            64'd20000,
            32'd2,
            32'd2000,
            32'd50
        );

        send_packet(
            1'b0,
            MESSAGE_QUOTE_UPDATE,
            SIDE_ASK,
            32'd234,
            64'd20100,
            32'd2,
            32'd2002,
            32'd50
        );

        expect_no_signal(
            10,
            "slot 1 remained in warm-up"
        );

        check_condition(
            dut.feature_engine_inst.sample_count[0] == 6'd32 &&
            dut.feature_engine_inst.sample_count[1] == 6'd1,
            "instrument histories remained independent"
        );

        // Test stage 11 increases slot zero's bid quantity.
        // Imbalance becomes 300 minus 100, which is 200.
        // Score 200 exceeds threshold 104 and produces BUY.
        send_packet(
            1'b0,
            MESSAGE_QUOTE_UPDATE,
            SIDE_BID,
            32'd235,
            64'd14000,
            32'd1,
            32'd1000,
            32'd300
        );

        expect_signal(
            3'd0,
            64'd14000,
            SIGNAL_BUY,
            64'sd200,
            64'sd104,
            "integrated BUY"
        );

        // Test stage 12 repeats sequence number 235.
        // The sequence tracker must reject the duplicate.
        // No additional trading signal may be produced.
        send_packet(
            1'b0,
            MESSAGE_QUOTE_UPDATE,
            SIDE_BID,
            32'd235,
            64'd14100,
            32'd1,
            32'd1000,
            32'd900
        );

        expect_no_signal(
            15,
            "duplicate quote rejected"
        );

        check_condition(
            dut.duplicate_count == 32'd1,
            "duplicate counter incremented"
        );

        // Test stage 13 sends an older sequence number.
        // The sequence tracker rejects the out-of-order quote.
        // The stored bid quantity must remain unchanged.
        send_packet(
            1'b0,
            MESSAGE_QUOTE_UPDATE,
            SIDE_BID,
            32'd234,
            64'd14200,
            32'd1,
            32'd1000,
            32'd900
        );

        expect_no_signal(
            15,
            "out-of-order quote rejected"
        );

        check_condition(
            dut.out_of_order_count == 32'd1,
            "out-of-order counter incremented"
        );

        // Test stage 14 skips sequences 236 and 237.
        // Sequence 238 is accepted and resynchronises tracking.
        // Ask dominance produces score negative 200 and SELL.
        send_packet(
            1'b0,
            MESSAGE_QUOTE_UPDATE,
            SIDE_ASK,
            32'd238,
            64'd15000,
            32'd1,
            32'd1002,
            32'd500
        );

        expect_signal(
            3'd0,
            64'd15000,
            SIGNAL_SELL,
            -64'sd200,
            64'sd104,
            "missing-sequence SELL"
        );

        check_condition(
            dut.missing_count == 32'd2,
            "missing sequence count recorded"
        );

        // Test stage 15 balances both quantities at 500.
        // The direction score returns to zero.
        // The decision must return to HOLD.
        send_packet(
            1'b0,
            MESSAGE_QUOTE_UPDATE,
            SIDE_BID,
            32'd239,
            64'd16000,
            32'd1,
            32'd1000,
            32'd500
        );

        expect_signal(
            3'd0,
            64'd16000,
            SIGNAL_HOLD,
            64'sd0,
            64'sd104,
            "integrated HOLD after SELL"
        );

        // Test stage 16 ends the active stream.
        // No later quote may reach the trading pipeline.
        // stream_active must return low.
        send_packet(
            1'b0,
            MESSAGE_STREAM_END,
            SIDE_BID,
            32'd0,
            64'd17000,
            32'd0,
            32'd0,
            32'd0
        );

        expect_no_signal(
            10,
            "STREAM_END produced no signal"
        );

        check_condition(
            dut.stream_active == 1'b0,
            "STREAM_END deactivated pipeline"
        );

        send_packet(
            1'b0,
            MESSAGE_QUOTE_UPDATE,
            SIDE_BID,
            32'd240,
            64'd17100,
            32'd1,
            32'd1000,
            32'd900
        );

        expect_no_signal(
            12,
            "quote after STREAM_END ignored"
        );

        // Test stage 17 starts another stream.
        // All counters and feature states must clear.
        // No previous-stream information may remain.
        send_packet(
            1'b0,
            MESSAGE_STREAM_START,
            SIDE_BID,
            32'd0,
            64'd18000,
            32'd0,
            32'd0,
            32'd0
        );

        expect_no_signal(
            8,
            "new stream produced no stale decision"
        );

        check_condition(
            dut.sequence_initialized == 1'b0 &&
            dut.missing_count == 32'd0 &&
            dut.duplicate_count == 32'd0 &&
            dut.out_of_order_count == 32'd0 &&
            dut.feature_engine_inst.sample_count[0] == 6'd0 &&
            dut.feature_engine_inst.sample_count[1] == 6'd0,
            "new stream cleared integrated state"
        );

        // Test stage 18 asserts reset while active.
        // Final outputs and all internal state must clear.
        // The test ends after reporting the result.
        @(negedge clk);
        resetn = 1'b0;

        @(posedge clk);
        #1;

        check_condition(
            signal_valid == 1'b0 &&
            signal_instrument_slot == 3'd0 &&
            signal_timestamp_ns == 64'd0 &&
            trade_signal == SIGNAL_HOLD &&
            direction_score == 64'sd0 &&
            required_score == 64'sd0,
            "active reset outputs"
        );

        check_condition(
            dut.stream_active == 1'b0 &&
            dut.sequence_initialized == 1'b0 &&
            dut.feature_engine_inst.sample_count[0] == 6'd0,
            "active reset internal state"
        );

        if (errors == 0) begin
            $display("All hft_engine_wrapper tests passed.");
        end
        else begin
            $fatal(
                1,
                "%0d hft_engine_wrapper tests failed.",
                errors
            );
        end

        $finish;
    end

endmodule
