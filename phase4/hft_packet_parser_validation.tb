`timescale 1ns / 1ps

module hft_packet_parser_validation_tb;

    logic         aclk;
    logic         aresetn;

    logic [31:0]  s_axis_tdata;
    logic [3:0]   s_axis_tkeep;
    logic         s_axis_tvalid;
    logic         s_axis_tready;
    logic         s_axis_tlast;

    logic [31:0]  m_axis_tdata;
    logic [3:0]   m_axis_tkeep;
    logic         m_axis_tvalid;
    logic         m_axis_tready;
    logic         m_axis_tlast;

    logic [31:0]  magic;
    logic [7:0]   version;
    logic [7:0]   message_type;
    logic [7:0]   side;
    logic [7:0]   reserved_field;
    logic [31:0]  seq;
    logic [63:0]  timestamp_ns;
    logic [31:0]  instrument_id;
    logic [31:0]  price_ticks;
    logic [31:0]  quantity;

    logic [2:0]   word_index;
    logic         packet_valid;
    logic         packet_error;
    logic [7:0]   error_flags;

    hft_packet_parser dut (
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
        .quantity       (quantity),
        .word_index     (word_index),
        .packet_valid   (packet_valid),
        .packet_error   (packet_error),
        .error_flags    (error_flags)
    );

    initial begin
        aclk = 1'b0;
        forever #5 aclk = ~aclk;
    end

    task automatic send_beat(
        input logic [31:0] data,
        input logic [3:0]  keep,
        input logic        last
    );
        begin
            @(negedge aclk);
            s_axis_tdata  = data;
            s_axis_tkeep  = keep;
            s_axis_tlast  = last;
            s_axis_tvalid = 1'b1;

            @(posedge aclk);
            while (!s_axis_tready)
                @(posedge aclk);

            @(negedge aclk);
            s_axis_tvalid = 1'b0;
            s_axis_tlast  = 1'b0;
        end
    endtask

    task automatic send_packet(
        input logic [31:0] magic_word,
        input logic [31:0] header_word,
        input logic        inject_bad_keep,
        input integer      bad_keep_index,
        input logic        inject_early_tlast,
        input integer      early_tlast_index,
        input logic        final_tlast
    );
        logic [31:0] data;
        logic [3:0]  keep;
        logic        last;
        integer      beat;
        begin
            for (beat = 0; beat < 8; beat = beat + 1) begin
                case (beat)
                    0: data = magic_word;
                    1: data = header_word;
                    2: data = 32'h04030201;
                    3: data = 32'h14131211;
                    4: data = 32'h18171615;
                    5: data = 32'h24232221;
                    6: data = 32'h34333231;
                    7: data = 32'h44434241;
                    default: data = 32'b0;
                endcase

                if (inject_bad_keep && (beat == bad_keep_index))
                    keep = 4'b0111;
                else
                    keep = 4'hF;

                if (beat == 7)
                    last = final_tlast;
                else if (inject_early_tlast && (beat == early_tlast_index))
                    last = 1'b1;
                else
                    last = 1'b0;

                send_beat(data, keep, last);

                if ((beat != 7) && (packet_valid || packet_error))
                    $fatal(1, "Completion pulse occurred before beat 7");
            end
        end
    endtask

    task automatic check_result(
        input logic       expected_valid,
        input logic       expected_error,
        input logic [7:0] expected_flags,
        input integer     test_number
    );
        begin
            if (packet_valid !== expected_valid)
                $fatal(
                    1,
                    "Test %0d packet_valid mismatch: expected=%0b actual=%0b",
                    test_number,
                    expected_valid,
                    packet_valid
                );

            if (packet_error !== expected_error)
                $fatal(
                    1,
                    "Test %0d packet_error mismatch: expected=%0b actual=%0b",
                    test_number,
                    expected_error,
                    packet_error
                );

            if (error_flags !== expected_flags)
                $fatal(
                    1,
                    "Test %0d error_flags mismatch: expected=%02h actual=%02h",
                    test_number,
                    expected_flags,
                    error_flags
                );

            if (word_index !== 3'd0)
                $fatal(
                    1,
                    "Test %0d counter did not wrap: word_index=%0d",
                    test_number,
                    word_index
                );

            // Verify that the completion outputs are one-clock pulses.
            @(posedge aclk);
            #1;

            if (packet_valid || packet_error || (error_flags != 8'b0))
                $fatal(1, "Test %0d completion output did not clear", test_number);
        end
    endtask

    initial begin
        aresetn        = 1'b0;
        s_axis_tdata   = 32'b0;
        s_axis_tkeep   = 4'b0;
        s_axis_tvalid  = 1'b0;
        s_axis_tlast   = 1'b0;
        m_axis_tready  = 1'b1;

        repeat (3) @(posedge aclk);
        @(negedge aclk);
        aresetn = 1'b1;

        // 1. Valid quote update: version 1, type 1, ASK side 1, reserved 0.
        send_packet(
            32'h31544648,
            32'h00010101,
            1'b0,
            0,
            1'b0,
            0,
            1'b1
        );
        check_result(1'b1, 1'b0, 8'h00, 1);

        // 2. Valid STREAM_START: version 1, type 4, control side 0.
        send_packet(
            32'h31544648,
            32'h00000401,
            1'b0,
            0,
            1'b0,
            0,
            1'b1
        );
        check_result(1'b1, 1'b0, 8'h00, 2);

        // 3. Invalid magic.
        send_packet(
            32'hDEADBEEF,
            32'h00010101,
            1'b0,
            0,
            1'b0,
            0,
            1'b1
        );
        check_result(1'b0, 1'b1, 8'h01, 3);

        // 4. Invalid version.
        send_packet(
            32'h31544648,
            32'h00010102,
            1'b0,
            0,
            1'b0,
            0,
            1'b1
        );
        check_result(1'b0, 1'b1, 8'h02, 4);

        // 5. Unsupported message type 9.
        send_packet(
            32'h31544648,
            32'h00000901,
            1'b0,
            0,
            1'b0,
            0,
            1'b1
        );
        check_result(1'b0, 1'b1, 8'h04, 5);

        // 6. Invalid quote side 2.
        send_packet(
            32'h31544648,
            32'h00020101,
            1'b0,
            0,
            1'b0,
            0,
            1'b1
        );
        check_result(1'b0, 1'b1, 8'h08, 6);

        // 7. Reserved byte must be zero.
        send_packet(
            32'h31544648,
            32'h01010101,
            1'b0,
            0,
            1'b0,
            0,
            1'b1
        );
        check_result(1'b0, 1'b1, 8'h10, 7);

        // 8. Beat 5 has an incomplete TKEEP mask.
        send_packet(
            32'h31544648,
            32'h00010101,
            1'b1,
            5,
            1'b0,
            0,
            1'b1
        );
        check_result(1'b0, 1'b1, 8'h20, 8);

        // 9. TLAST is asserted early on beat 3.
        send_packet(
            32'h31544648,
            32'h00010101,
            1'b0,
            0,
            1'b1,
            3,
            1'b1
        );
        check_result(1'b0, 1'b1, 8'h40, 9);

        // 10. TLAST is missing on beat 7.
        send_packet(
            32'h31544648,
            32'h00010101,
            1'b0,
            0,
            1'b0,
            0,
            1'b0
        );
        check_result(1'b0, 1'b1, 8'h80, 10);

        // 11. Multiple errors must accumulate across different beats.
        send_packet(
            32'hDEADBEEF,
            32'h00010102,
            1'b1,
            5,
            1'b1,
            3,
            1'b0
        );
        check_result(1'b0, 1'b1, 8'hE3, 11);

        // 12. A valid packet after errors proves the accumulator was cleared.
        send_packet(
            32'h31544648,
            32'h00000501,
            1'b0,
            0,
            1'b0,
            0,
            1'b1
        );
        check_result(1'b1, 1'b0, 8'h00, 12);

        $display("Phase 4.5 packet validation test: PASS");
        $finish;
    end

endmodule
