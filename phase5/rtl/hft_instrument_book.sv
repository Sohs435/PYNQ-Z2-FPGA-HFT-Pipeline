module hft_instrument_book (
    input logic clk,
    input logic resetn,

    input logic stream_start_pulse,
    input logic stream_end_pulse,

    input logic tracked_quote_valid,
    input logic [2:0] tracked_instrument_slot,
    input logic [7:0] tracked_side,
    input logic [31:0] tracked_seq,
    input logic [63:0] tracked_timestamp_ns,
    input logic [31:0] tracked_price_ticks,
    input logic [31:0] tracked_quantity,

    output logic book_update_valid,
    output logic [2:0] book_instrument_slot,
    output logic [31:0] book_seq,
    output logic [63:0] book_timestamp_ns,

    output logic [31:0] book_bid_price,
    output logic [31:0] book_bid_quantity,
    output logic [31:0] book_ask_price,
    output logic [31:0] book_ask_quantity,

    output logic book_valid,
    output logic crossed_book
);

    // These constants define the two supported quote sides.
    // A bid updates the stored buying side of the order book.
    // An ask updates the stored selling side of the order book.
    localparam logic [7:0] SIDE_BID = 8'd0;
    localparam logic [7:0] SIDE_ASK = 8'd1;

    // These arrays store the latest bid state for all five instruments.
    // Each array index corresponds to the instrument slot from Phase 5.2.
    // Price and quantity are updated whenever a tracked bid quote arrives.
    logic [31:0] bid_price_mem [0:4];
    logic [31:0] bid_quantity_mem [0:4];

    // These arrays store the latest ask state for all five instruments.
    // Each instrument keeps its ask state independently of the others.
    // Price and quantity are updated whenever a tracked ask quote arrives.
    logic [31:0] ask_price_mem [0:4];
    logic [31:0] ask_quantity_mem [0:4];

    // These flags record whether each side has received at least one quote.
    // A complete book requires both its bid and ask flags to be asserted.
    // STREAM_START and reset clear all initialization flags.
    logic bid_initialized_mem [0:4];
    logic ask_initialized_mem [0:4];

    // This loop variable is used to reset all five instrument books.
    // Synthesis unrolls the fixed five-iteration loop into parallel hardware.
    // It does not create a loop that executes repeatedly at runtime.
    integer i;

    // This sequential block stores books and produces registered snapshots.
    // Every accepted quote updates exactly one side of one instrument book.
    // Stream-control events receive priority over incoming quote updates.
    always_ff @(posedge clk) begin

        // Reset clears all book memories, initialization flags, and outputs.
        // Because resetn is checked inside always_ff, the reset is synchronous.
        // The clearing occurs on a rising clock edge while resetn is low.
        if (!resetn) begin
            for (i = 0; i < 5; i = i + 1) begin
                bid_price_mem[i] <= '0;
                bid_quantity_mem[i] <= '0;
                ask_price_mem[i] <= '0;
                ask_quantity_mem[i] <= '0;
                bid_initialized_mem[i] <= 1'b0;
                ask_initialized_mem[i] <= 1'b0;
            end

            book_update_valid <= 1'b0;
            book_instrument_slot <= '0;
            book_seq <= '0;
            book_timestamp_ns <= '0;

            book_bid_price <= '0;
            book_bid_quantity <= '0;
            book_ask_price <= '0;
            book_ask_quantity <= '0;

            book_valid <= 1'b0;
            crossed_book <= 1'b0;
        end
        else begin

            // book_update_valid is a one-clock pulse for each accepted quote.
            // It defaults to zero and is asserted again inside an update branch.
            // Other output fields retain their previous values when it is low.
            book_update_valid <= 1'b0;

            // A new stream must not reuse prices from the previous stream.
            // This loop clears all five books and their initialization flags.
            // The next bid and ask updates rebuild each book from empty state.
            if (stream_start_pulse) begin
                for (i = 0; i < 5; i = i + 1) begin
                    bid_price_mem[i] <= '0;
                    bid_quantity_mem[i] <= '0;
                    ask_price_mem[i] <= '0;
                    ask_quantity_mem[i] <= '0;
                    bid_initialized_mem[i] <= 1'b0;
                    ask_initialized_mem[i] <= 1'b0;
                end

                book_instrument_slot <= '0;
                book_seq <= '0;
                book_timestamp_ns <= '0;

                book_bid_price <= '0;
                book_bid_quantity <= '0;
                book_ask_price <= '0;
                book_ask_quantity <= '0;

                book_valid <= 1'b0;
                crossed_book <= 1'b0;
            end

            // STREAM_END prevents a book update during the end event.
            // The stored books remain available for inspection after the stream.
            // A later STREAM_START clears them before processing new quotes.
            else if (stream_end_pulse) begin
                book_valid <= 1'b0;
                crossed_book <= 1'b0;
            end

            // Only tracked quotes with slots zero through four are processed.
            // The slot guard prevents an invalid unpacked-array index.
            // Invalid slots and cycles without a quote are silently ignored.
            else if (
                tracked_quote_valid &&
                tracked_instrument_slot < 3'd5
            ) begin

                // A bid quote replaces the stored bid for the selected instrument.
                // The existing ask is combined with the incoming bid in the output.
                // Using the input bid avoids outputting the old nonblocking value.
                if (tracked_side == SIDE_BID) begin
                    bid_price_mem[tracked_instrument_slot] <=
                        tracked_price_ticks;

                    bid_quantity_mem[tracked_instrument_slot] <=
                        tracked_quantity;

                    bid_initialized_mem[tracked_instrument_slot] <=
                        1'b1;

                    book_update_valid <= 1'b1;
                    book_instrument_slot <= tracked_instrument_slot;
                    book_seq <= tracked_seq;
                    book_timestamp_ns <= tracked_timestamp_ns;

                    book_bid_price <= tracked_price_ticks;
                    book_bid_quantity <= tracked_quantity;

                    book_ask_price <=
                        ask_price_mem[tracked_instrument_slot];

                    book_ask_quantity <=
                        ask_quantity_mem[tracked_instrument_slot];

                    book_valid <=
                        ask_initialized_mem[tracked_instrument_slot];

                    crossed_book <=
                        ask_initialized_mem[tracked_instrument_slot] &&
                        (
                            ask_price_mem[tracked_instrument_slot] <
                            tracked_price_ticks
                        );
                end

                // An ask quote replaces the stored ask for the selected instrument.
                // The existing bid is combined with the incoming ask in the output.
                // Using the input ask avoids outputting the old nonblocking value.
                else if (tracked_side == SIDE_ASK) begin
                    ask_price_mem[tracked_instrument_slot] <=
                        tracked_price_ticks;

                    ask_quantity_mem[tracked_instrument_slot] <=
                        tracked_quantity;

                    ask_initialized_mem[tracked_instrument_slot] <=
                        1'b1;

                    book_update_valid <= 1'b1;
                    book_instrument_slot <= tracked_instrument_slot;
                    book_seq <= tracked_seq;
                    book_timestamp_ns <= tracked_timestamp_ns;

                    book_bid_price <=
                        bid_price_mem[tracked_instrument_slot];

                    book_bid_quantity <=
                        bid_quantity_mem[tracked_instrument_slot];

                    book_ask_price <= tracked_price_ticks;
                    book_ask_quantity <= tracked_quantity;

                    book_valid <=
                        bid_initialized_mem[tracked_instrument_slot];

                    crossed_book <=
                        bid_initialized_mem[tracked_instrument_slot] &&
                        (
                            tracked_price_ticks <
                            bid_price_mem[tracked_instrument_slot]
                        );
                end
            end
        end
    end

endmodule
