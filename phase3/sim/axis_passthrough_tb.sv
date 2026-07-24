`timescale 1ns / 1ps

module axis_passthrough_tb;

    localparam DATA_WIDTH = 32;

    logic                  aclk;
    logic                  aresetn;

    logic [DATA_WIDTH-1:0] s_axis_tdata;
    logic                  s_axis_tvalid;
    logic                  s_axis_tready;
    logic                  s_axis_tlast;

    logic [DATA_WIDTH-1:0] m_axis_tdata;
    logic                  m_axis_tvalid;
    logic                  m_axis_tready;
    logic                  m_axis_tlast;

    // Instantiate the module being tested.
    axis_passthrough #(
        .DATA_WIDTH(DATA_WIDTH)
    ) dut (
        .aclk          (aclk),
        .aresetn       (aresetn),

        .s_axis_tdata  (s_axis_tdata),
        .s_axis_tvalid (s_axis_tvalid),
        .s_axis_tready (s_axis_tready),
        .s_axis_tlast  (s_axis_tlast),

        .m_axis_tdata  (m_axis_tdata),
        .m_axis_tvalid (m_axis_tvalid),
        .m_axis_tready (m_axis_tready),
        .m_axis_tlast  (m_axis_tlast)
    );

    // Generate a 100 MHz clock:
    // 5 ns low + 5 ns high = 10 ns period.
    always #5 aclk = ~aclk;

    initial begin
        // Initial signal values
        aclk          = 1'b0;
        aresetn       = 1'b0;

        s_axis_tdata  = '0;
        s_axis_tvalid = 1'b0;
        s_axis_tlast  = 1'b0;

        m_axis_tready = 1'b0;


        // Keep reset active for three rising edges.
        repeat (3) @(posedge aclk);

        // Wait briefly for nonblocking assignments to update.
        #1;

        if (m_axis_tvalid !== 1'b0)
            $fatal(1, "RESET FAILED: m_axis_tvalid should be 0");

        // Change inputs on a falling edge so that they are stable
        // before the next rising edge.
        @(negedge aclk);
        aresetn       = 1'b1;
        m_axis_tready = 1'b1;

        s_axis_tdata  = 32'h1111_1111;
        s_axis_tvalid = 1'b1;
        s_axis_tlast  = 1'b0;

        // Input word is captured on this rising edge.
        @(posedge aclk);
        #1;

        if (m_axis_tvalid !== 1'b1)
            $fatal(1, "NORMAL TRANSFER FAILED: output valid is not 1");

        if (m_axis_tdata !== 32'h1111_1111)
            $fatal(1, "NORMAL TRANSFER FAILED: incorrect output data");

        if (m_axis_tlast !== 1'b0)
            $fatal(1, "NORMAL TRANSFER FAILED: TLAST should be 0");

        // The first word will leave while this second word enters.
        @(negedge aclk);
        s_axis_tdata = 32'h2222_2222;
        s_axis_tlast = 1'b1;

        @(posedge aclk);
        #1;

        if (m_axis_tdata !== 32'h2222_2222)
            $fatal(1, "REPLACEMENT FAILED: second word not loaded");

        if (m_axis_tlast !== 1'b1)
            $fatal(1, "REPLACEMENT FAILED: TLAST not copied");


        // Stall the S2MM DMA while the second word is stored.
        // Also attempt to send a third input word.
        @(negedge aclk);
        m_axis_tready = 1'b0;
        s_axis_tdata  = 32'h3333_3333;
        s_axis_tlast  = 1'b0;

        #1;

        if (s_axis_tready !== 1'b0)
            $fatal(1, "BACKPRESSURE FAILED: input ready should be 0");

        // Wait for two rising edges while S2MM remains stalled.
        repeat (2) begin
            @(posedge aclk);
            #1;

            if (m_axis_tdata !== 32'h2222_2222)
                $fatal(1, "BACKPRESSURE FAILED: output data changed");

            if (m_axis_tvalid !== 1'b1)
                $fatal(1, "BACKPRESSURE FAILED: output valid changed");

            if (m_axis_tlast !== 1'b1)
                $fatal(1, "BACKPRESSURE FAILED: TLAST changed");
        end

        @(negedge aclk);
        m_axis_tready = 1'b1;

        // On this edge, 2222_2222 leaves and 3333_3333 enters.
        @(posedge aclk);
        #1;

        if (m_axis_tdata !== 32'h3333_3333)
            $fatal(1, "DRAIN FAILED: waiting word not captured");

        if (m_axis_tvalid !== 1'b1)
            $fatal(1, "DRAIN FAILED: output should remain valid");

        @(negedge aclk);
        s_axis_tvalid = 1'b0;
        s_axis_tlast  = 1'b0;

        // The third word leaves without being replaced.
        @(posedge aclk);
        #1;

        if (m_axis_tvalid !== 1'b0)
            $fatal(1, "FINISH FAILED: output valid should clear");

        $display("ALL AXI4-STREAM TESTS PASSED");

        #20;
        $finish;
    end

endmodule
