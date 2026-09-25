module hft_feature_engine (
    input logic clk,
    input logic resetn,

    input logic stream_start_pulse,
    input logic stream_end_pulse,

    input logic book_update_valid,
    input logic [2:0] book_instrument_slot,
    input logic [63:0] book_timestamp_ns,

    input logic [31:0] book_bid_price,
    input logic [31:0] book_bid_quantity,
    input logic [31:0] book_ask_price,
    input logic [31:0] book_ask_quantity,

    input logic book_valid,
    input logic crossed_book,

    output logic feature_valid,
    output logic [2:0] feature_instrument_slot,
    output logic [63:0] feature_timestamp_ns,

    output logic signed [33:0] trend,
    output logic signed [32:0] quantity_imbalance,
    output logic [31:0] spread
);

    // Accept only complete and non-crossed books.
    // Instrument slots outside zero to four are rejected.
    // Every accepted update produces one midpoint sample.
    logic process_book_update;
    logic [32:0] midpoint2;

    assign process_book_update =
        book_update_valid &&
        book_valid &&
        !crossed_book &&
        (book_instrument_slot < 3'd5);

    assign midpoint2 =
        {1'b0, book_bid_price} +
        {1'b0, book_ask_price};

    // Store the latest eight midpoint samples per instrument.
    // fast_pointer identifies the oldest stored midpoint.
    // fast_sum stores the rolling sum of the eight entries.
    logic [32:0] fast_buffer [0:4][0:7];
    logic [2:0] fast_pointer [0:4];
    logic [35:0] fast_sum [0:4];

    // Store the latest 32 midpoint samples per instrument.
    // slow_pointer identifies the oldest stored midpoint.
    // slow_sum stores the rolling sum of the 32 entries.
    logic [32:0] slow_buffer [0:4][0:31];
    logic [4:0] slow_pointer [0:4];
    logic [37:0] slow_sum [0:4];

    // Track the number of samples received by each instrument.
    // The counter increases during the two warm-up states.
    // It saturates at 32 once both windows are complete.
    logic [5:0] sample_count [0:4];

    // Each instrument has its own current and next state.
    // Instruments can therefore warm up independently.
    // FEATURE_READY produces a feature for every update.
    typedef enum logic [1:0] {
        WARMUP_FAST,
        WARMUP_SLOW,
        FEATURE_READY
    } feature_state_t;

    feature_state_t current_state [0:4];
    feature_state_t next_state [0:4];

    // Stage 1 stores the input metadata and direct features.
    // The moving-average sums are updated in the same stage.
    // Stage 2 reads the newly updated registered sums.
    logic calculation_valid_s1;
    logic [2:0] instrument_slot_s1;
    logic [63:0] timestamp_s1;
    logic signed [32:0] quantity_imbalance_s1;
    logic [31:0] spread_s1;

    integer i;
    integer state_index;

    // Hold every instrument in its current state by default.
    // Only the instrument receiving an accepted update can transition.
    // The counter value determines when each warm-up stage finishes.
    always_comb begin
        for (
            state_index = 0;
            state_index < 5;
            state_index = state_index + 1
        ) begin
            next_state[state_index] = current_state[state_index];
        end

        if (process_book_update) begin
            case (current_state[book_instrument_slot])

                WARMUP_FAST: begin
                    if (sample_count[book_instrument_slot] == 6'd7) begin
                        next_state[book_instrument_slot] = WARMUP_SLOW;
                    end
                end

                WARMUP_SLOW: begin
                    if (sample_count[book_instrument_slot] == 6'd31) begin
                        next_state[book_instrument_slot] = FEATURE_READY;
                    end
                end

                FEATURE_READY: begin
                    next_state[book_instrument_slot] = FEATURE_READY;
                end

                default: begin
                    next_state[book_instrument_slot] = WARMUP_FAST;
                end

            endcase
        end
    end

    always_ff @(posedge clk) begin
        if (!resetn) begin
            for (i = 0; i < 5; i = i + 1) begin
                fast_sum[i] <= '0;
                slow_sum[i] <= '0;
                fast_pointer[i] <= '0;
                slow_pointer[i] <= '0;
                sample_count[i] <= '0;
                current_state[i] <= WARMUP_FAST;
            end

            calculation_valid_s1 <= 1'b0;
            instrument_slot_s1 <= '0;
            timestamp_s1 <= '0;
            quantity_imbalance_s1 <= '0;
            spread_s1 <= '0;

            feature_valid <= 1'b0;
            feature_instrument_slot <= '0;
            feature_timestamp_ns <= '0;
            trend <= '0;
            quantity_imbalance <= '0;
            spread <= '0;
        end
        else if (stream_start_pulse) begin

            // Clear all calculation state for the new stream.
            // Buffer entries do not need to be reset.
            // Warm-up overwrites each entry before it is removed.
            for (i = 0; i < 5; i = i + 1) begin
                fast_sum[i] <= '0;
                slow_sum[i] <= '0;
                fast_pointer[i] <= '0;
                slow_pointer[i] <= '0;
                sample_count[i] <= '0;
                current_state[i] <= WARMUP_FAST;
            end

            calculation_valid_s1 <= 1'b0;
            instrument_slot_s1 <= '0;
            timestamp_s1 <= '0;
            quantity_imbalance_s1 <= '0;
            spread_s1 <= '0;

            feature_valid <= 1'b0;
            feature_instrument_slot <= '0;
            feature_timestamp_ns <= '0;
            trend <= '0;
            quantity_imbalance <= '0;
            spread <= '0;
        end
        else if (stream_end_pulse) begin

            // Cancel any calculation remaining in the pipeline.
            // No feature is produced after the stream ends.
            // The next stream start clears all stored state.
            calculation_valid_s1 <= 1'b0;
            feature_valid <= 1'b0;
        end
        else begin

            // Register the next state for every instrument.
            // Instruments without an update remain in their current state.
            // Only the selected instrument can change state.
            for (i = 0; i < 5; i = i + 1) begin
                current_state[i] <= next_state[i];
            end

            // Stage 2 produces the final feature outputs.
            // Division by eight and 32 uses right shifts.
            // Trend is the fast average minus the slow average.
            feature_valid <= calculation_valid_s1;

            if (calculation_valid_s1) begin
                feature_instrument_slot <= instrument_slot_s1;
                feature_timestamp_ns <= timestamp_s1;

                trend <=
                    $signed({
                        1'b0,
                        fast_sum[instrument_slot_s1][35:3]
                    }) -
                    $signed({
                        1'b0,
                        slow_sum[instrument_slot_s1][37:5]
                    });

                quantity_imbalance <= quantity_imbalance_s1;
                spread <= spread_s1;
            end

            calculation_valid_s1 <= 1'b0;

            // Stage 1 accepts one valid book update.
            // Metadata, quantity imbalance and spread are registered.
            // The selected instrument's datapath is then updated.
            if (process_book_update) begin
                instrument_slot_s1 <= book_instrument_slot;
                timestamp_s1 <= book_timestamp_ns;

                quantity_imbalance_s1 <=
                    $signed({1'b0, book_bid_quantity}) -
                    $signed({1'b0, book_ask_quantity});

                spread_s1 <=
                    book_ask_price -
                    book_bid_price;

                case (current_state[book_instrument_slot])

                    // Samples one through eight fill both buffers.
                    // No stored midpoint is removed in this state.
                    // The next-state block detects sample eight.
                    WARMUP_FAST: begin
                        fast_sum[book_instrument_slot] <=
                            fast_sum[book_instrument_slot] +
                            midpoint2;

                        slow_sum[book_instrument_slot] <=
                            slow_sum[book_instrument_slot] +
                            midpoint2;

                        fast_buffer[book_instrument_slot]
                                   [fast_pointer[book_instrument_slot]]
                                   <= midpoint2;

                        slow_buffer[book_instrument_slot]
                                   [slow_pointer[book_instrument_slot]]
                                   <= midpoint2;

                        fast_pointer[book_instrument_slot] <=
                            fast_pointer[book_instrument_slot] +
                            3'd1;

                        slow_pointer[book_instrument_slot] <=
                            slow_pointer[book_instrument_slot] +
                            5'd1;

                        sample_count[book_instrument_slot] <=
                            sample_count[book_instrument_slot] +
                            6'd1;
                    end

                    // Samples nine through 32 roll the fast buffer.
                    // The slow buffer continues filling without subtraction.
                    // Sample 32 enables the first feature calculation.
                    WARMUP_SLOW: begin
                        fast_sum[book_instrument_slot] <=
                            fast_sum[book_instrument_slot] -
                            fast_buffer[book_instrument_slot]
                                       [fast_pointer[book_instrument_slot]] +
                            midpoint2;

                        slow_sum[book_instrument_slot] <=
                            slow_sum[book_instrument_slot] +
                            midpoint2;

                        fast_buffer[book_instrument_slot]
                                   [fast_pointer[book_instrument_slot]]
                                   <= midpoint2;

                        slow_buffer[book_instrument_slot]
                                   [slow_pointer[book_instrument_slot]]
                                   <= midpoint2;

                        fast_pointer[book_instrument_slot] <=
                            fast_pointer[book_instrument_slot] +
                            3'd1;

                        slow_pointer[book_instrument_slot] <=
                            slow_pointer[book_instrument_slot] +
                            5'd1;

                        sample_count[book_instrument_slot] <=
                            sample_count[book_instrument_slot] +
                            6'd1;

                        if (sample_count[book_instrument_slot] == 6'd31) begin
                            calculation_valid_s1 <= 1'b1;
                        end
                    end

                    // Both moving-average buffers are now full.
                    // Each update removes the oldest stored samples.
                    // Every accepted update produces a valid calculation.
                    FEATURE_READY: begin
                        fast_sum[book_instrument_slot] <=
                            fast_sum[book_instrument_slot] -
                            fast_buffer[book_instrument_slot]
                                       [fast_pointer[book_instrument_slot]] +
                            midpoint2;

                        slow_sum[book_instrument_slot] <=
                            slow_sum[book_instrument_slot] -
                            slow_buffer[book_instrument_slot]
                                       [slow_pointer[book_instrument_slot]] +
                            midpoint2;

                        fast_buffer[book_instrument_slot]
                                   [fast_pointer[book_instrument_slot]]
                                   <= midpoint2;

                        slow_buffer[book_instrument_slot]
                                   [slow_pointer[book_instrument_slot]]
                                   <= midpoint2;

                        fast_pointer[book_instrument_slot] <=
                            fast_pointer[book_instrument_slot] +
                            3'd1;

                        slow_pointer[book_instrument_slot] <=
                            slow_pointer[book_instrument_slot] +
                            5'd1;

                        sample_count[book_instrument_slot] <= 6'd32;
                        calculation_valid_s1 <= 1'b1;
                    end

                    // Reset the selected instrument's datapath.
                    // Its next state returns to WARMUP_FAST.
                    // No feature is produced during recovery.
                    default: begin
                        fast_sum[book_instrument_slot] <= '0;
                        slow_sum[book_instrument_slot] <= '0;
                        fast_pointer[book_instrument_slot] <= '0;
                        slow_pointer[book_instrument_slot] <= '0;
                        sample_count[book_instrument_slot] <= '0;
                    end

                endcase
            end
        end
    end

endmodule
