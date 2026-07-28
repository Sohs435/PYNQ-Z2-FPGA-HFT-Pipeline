# Phase 5 — FPGA Trading Engine

## 5.1 Weighted Trading Decision Model

### Objective

Phase 5 converts the validated and decoded market data produced by Phase 4 into
real-time trading decisions. Phase 5.1 defines and verifies the final weighted
decision block that converts three precomputed market features into a `BUY`,
`SELL`, or `HOLD` signal.

The three input features are:

- Price trend, calculated from the difference between fast and slow moving
  averages.
- Bid/ask quantity imbalance.
- Bid–ask spread.

The feature-extraction, instrument-book, sequence-tracking, and time-sampling
blocks are implemented in later subphases. The `weighted_decision` module assumes
that its inputs have already been checked and are valid whenever
`feature_valid` is asserted.

### Initial operating configuration

The initial complete Phase 5 system will use the following operating targets:

| Setting | Initial value |
| --- | ---: |
| Total market-data rate | 20,000 packets/s |
| Number of instruments | 5 |
| Average rate per instrument | 4,000 packets/s |
| Decision rate per instrument | 2,000 decisions/s |
| Aggregate decision rate | 10,000 decisions/s |
| Decision period | 500 µs |
| Fast moving-average window | 8 samples, or 4 ms |
| Slow moving-average window | 32 samples, or 16 ms |

These timing values do not appear inside `weighted_decision`. They determine how
often the future feature engine asserts `feature_valid`.

---

### Trading model

The directional score is calculated as:

```text
direction_score = (TREND_WEIGHT * trend) + (IMBALANCE_WEIGHT * quantity_imbalance)
```

The required score is calculated as:

```text
required_score = BASE_THRESHOLD + (SPREAD_WEIGHT * spread)
```

The decision rules are:

```text
direction_score >  required_score -> BUY
direction_score < -required_score -> SELL
otherwise -> HOLD
```

The spread increases the confidence required to trade. A wider spread therefore makes both `BUY` and `SELL` decisions less likely without creating an artificial directional bias.

### Initial model constants

| Constant | Value | Purpose |
| --- | ---: | --- |
| `TREND_WEIGHT` | 4 | Weight applied to the moving-average trend |
| `IMBALANCE_WEIGHT` | 1 | Weight applied to quantity imbalance |
| `SPREAD_WEIGHT` | 2 | Amount added to the threshold per spread tick |
| `BASE_THRESHOLD` | 100 | Minimum absolute evidence required to trade |

These are initial verification values. They are parameters so that later
experiments can change them without modifying the decision logic.

### Trading-signal encoding

| Signal | Encoding |
| --- | --- |
| `HOLD` | `2'b00` |
| `BUY` | `2'b01` |
| `SELL` | `2'b10` |

---

### Module interface

| Signal | Direction | Width | Description |
| --- | --- | ---: | --- |
| `clk` | Input | 1 | FPGA clock |
| `resetn` | Input | 1 | Active-low synchronous reset |
| `feature_valid` | Input | 1 | Marks one valid input feature set |
| `instrument_slot` | Input | 3 | Identifies one of up to eight instrument slots |
| `feature_timestamp_ns` | Input | 64 | Timestamp associated with the feature set |
| `trend` | Input | 34 signed | Fast moving average minus slow moving average |
| `quantity_imbalance` | Input | 33 signed | Bid quantity minus ask quantity |
| `spread` | Input | 32 unsigned | Ask price minus bid price |
| `signal_valid` | Output | 1 | Marks one valid output decision |
| `signal_instrument_slot` | Output | 3 | Instrument associated with the decision |
| `signal_timestamp_ns` | Output | 64 | Timestamp associated with the decision |
| `trade_signal` | Output | 2 | Encoded `HOLD`, `BUY`, or `SELL` decision |
| `direction_score` | Output | 64 signed | Registered weighted directional score |
| `required_score` | Output | 64 signed | Registered spread-adjusted threshold |

The score datapath uses signed 64-bit registers. This provides sufficient
headroom for the current feature and weight widths and avoids overflow in the
initial model.

---

### Pipeline architecture

The module uses three registered stages:

| Stage | Operation |
| --- | --- |
| Stage 1 | Multiply trend, imbalance, and spread by their weights |
| Stage 2 | Add the directional products and calculate the required threshold |
| Stage 3 | Compare the scores and register `BUY`, `SELL`, or `HOLD` |

The instrument slot, timestamp, and valid bit pass through matching registers.
This ensures that the metadata at the output belongs to the same feature set as
the decision.

Once the pipeline is full, it can accept one feature set and produce one
decision on every clock cycle.

---

### `weighted_decision.sv`

```systemverilog
`timescale 1ns / 1ps

module weighted_decision #(
    parameter logic signed [15:0] TREND_WEIGHT       = 16'sd4,
    parameter logic signed [15:0] IMBALANCE_WEIGHT   = 16'sd1,
    parameter logic        [15:0] SPREAD_WEIGHT      = 16'd2,
    parameter logic signed [63:0] BASE_THRESHOLD     = 64'sd100
) (
    input logic clk,
    input logic resetn,

    input logic feature_valid,
    input logic [2:0] instrument_slot,
    input logic [63:0] feature_timestamp_ns,

    input logic signed [33:0] trend,
    input logic signed [32:0] quantity_imbalance,
    input logic        [31:0] spread,

    output logic signal_valid,
    output logic [2:0] signal_instrument_slot,
    output logic [63:0] signal_timestamp_ns,

    output logic [1:0] trade_signal,
    output logic signed [63:0] direction_score,
    output logic signed [63:0] required_score
);

    // Stage 1: weighted products
    logic signed [63:0] trend_product_s1;
    logic signed [63:0] imbalance_product_s1;
    logic signed [63:0] spread_product_s1;

    logic        valid_s1;
    logic [2:0]  instrument_slot_s1;
    logic [63:0] timestamp_s1;

    // Stage 2: accumulated scores
    logic signed [63:0] direction_score_s2;
    logic signed [63:0] required_score_s2;

    logic        valid_s2;
    logic [2:0]  instrument_slot_s2;
    logic [63:0] timestamp_s2;

    localparam logic [1:0] SIGNAL_HOLD = 2'b00;
    localparam logic [1:0] SIGNAL_BUY  = 2'b01;
    localparam logic [1:0] SIGNAL_SELL = 2'b10;

    always_ff @(posedge clk) begin
        if (!resetn) begin
            // Stage 1
            trend_product_s1       <= '0;
            imbalance_product_s1   <= '0;
            spread_product_s1      <= '0;
            valid_s1               <= 1'b0;
            instrument_slot_s1     <= '0;
            timestamp_s1           <= '0;

            // Stage 2
            direction_score_s2     <= '0;
            required_score_s2      <= '0;
            valid_s2               <= 1'b0;
            instrument_slot_s2     <= '0;
            timestamp_s2           <= '0;

            // Stage 3
            signal_valid           <= 1'b0;
            signal_instrument_slot <= '0;
            signal_timestamp_ns    <= '0;
            trade_signal           <= SIGNAL_HOLD;
            direction_score        <= '0;
            required_score         <= '0;
        end
        else begin
            // Stage 1: weighted multiplications
            trend_product_s1 <=
                $signed(trend) * $signed(TREND_WEIGHT);

            imbalance_product_s1 <=
                $signed(quantity_imbalance) *
                $signed(IMBALANCE_WEIGHT);

            spread_product_s1 <=
                $signed({1'b0, spread}) *
                $signed({1'b0, SPREAD_WEIGHT});

            valid_s1           <= feature_valid;
            instrument_slot_s1 <= instrument_slot;
            timestamp_s1       <= feature_timestamp_ns;

            // Stage 2: score and threshold calculation
            direction_score_s2 <=
                trend_product_s1 + imbalance_product_s1;

            required_score_s2 <=
                BASE_THRESHOLD + spread_product_s1;

            valid_s2           <= valid_s1;
            instrument_slot_s2 <= instrument_slot_s1;
            timestamp_s2       <= timestamp_s1;

            // Stage 3: register scores and metadata
            signal_valid           <= valid_s2;
            signal_instrument_slot <= instrument_slot_s2;
            signal_timestamp_ns    <= timestamp_s2;
            direction_score        <= direction_score_s2;
            required_score         <= required_score_s2;

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
```

#### What each RTL section does

**Parameter block**

The parameter block defines the initial weights and base threshold. Using
parameters keeps the arithmetic structure unchanged while allowing the model
constants to be adjusted during later experiments.

**Feature inputs**

`trend` and `quantity_imbalance` are signed because either feature can indicate
upward/buying pressure or downward/selling pressure. `spread` is unsigned
because a valid bid–ask spread cannot be negative.

**Pipeline registers**

The `_s1` registers hold the three multiplication results. The `_s2` registers
hold the final directional score and required threshold. Separate valid,
instrument, and timestamp registers maintain transaction alignment through the
pipeline.

**Reset branch**

The active-low synchronous reset clears every pipeline stage and forces the
output decision to `HOLD`. Because the reset is synchronous, it takes effect on
a rising clock edge while `resetn` is low.

**Stage 1**

Stage 1 performs the three weighted multiplications. Explicit signed casts are
used for the directional features. A leading zero is added to `spread` and
`SPREAD_WEIGHT` before their signed casts so they remain positive signed
quantities.

Stage 1 also registers `feature_valid`, the instrument slot, and the timestamp.

**Stage 2**

Stage 2 adds the weighted trend and imbalance to form `direction_score_s2`. It
also adds the weighted spread to `BASE_THRESHOLD` to form
`required_score_s2`.

The Stage 1 valid bit and metadata are advanced into their Stage 2 registers on
the same clock.

**Stage 3**

Stage 3 copies the scores and metadata to the module outputs. When `valid_s2` is
high, it compares the directional score against both the positive and negative
required thresholds.

If no valid Stage 2 transaction is present, `signal_valid` is low and
`trade_signal` is forced to `HOLD`.

---

### Verification approach

The testbench verifies:

1. Synchronous reset behaviour.
2. A positive score that produces `BUY`.
3. A negative score that produces `SELL`.
4. A score inside the threshold range that produces `HOLD`.
5. Signed multiplication and addition.
6. Spread-adjusted threshold calculation.
7. Instrument-slot and timestamp alignment.
8. Three back-to-back input transactions.
9. One-decision-per-clock pipeline throughput.
10. Correct deassertion of `signal_valid` after the pipeline drains.

### `weighted_decision_tb.sv`

```systemverilog
`timescale 1ns / 1ps

module weighted_decision_tb;

    localparam logic [1:0] SIGNAL_HOLD = 2'b00;
    localparam logic [1:0] SIGNAL_BUY  = 2'b01;
    localparam logic [1:0] SIGNAL_SELL = 2'b10;

    logic clk;
    logic resetn;

    logic               feature_valid;
    logic [2:0]         instrument_slot;
    logic [63:0]        feature_timestamp_ns;
    logic signed [33:0] trend;
    logic signed [32:0] quantity_imbalance;
    logic        [31:0] spread;

    logic               signal_valid;
    logic [2:0]         signal_instrument_slot;
    logic [63:0]        signal_timestamp_ns;
    logic [1:0]         trade_signal;
    logic signed [63:0] direction_score;
    logic signed [63:0] required_score;

    weighted_decision dut (
        .clk                    (clk),
        .resetn                 (resetn),

        .feature_valid          (feature_valid),
        .instrument_slot        (instrument_slot),
        .feature_timestamp_ns   (feature_timestamp_ns),

        .trend                  (trend),
        .quantity_imbalance     (quantity_imbalance),
        .spread                 (spread),

        .signal_valid           (signal_valid),
        .signal_instrument_slot (signal_instrument_slot),
        .signal_timestamp_ns    (signal_timestamp_ns),

        .trade_signal           (trade_signal),
        .direction_score        (direction_score),
        .required_score         (required_score)
    );

    // Generate a 100 MHz clock.
    initial begin
        clk = 1'b0;
        forever #5 clk = ~clk;
    end

    task automatic send_feature (
        input logic [2:0]         test_slot,
        input logic [63:0]        test_timestamp,
        input logic signed [33:0] test_trend,
        input logic signed [32:0] test_imbalance,
        input logic [31:0]        test_spread
    );
        begin
            @(negedge clk);

            feature_valid        = 1'b1;
            instrument_slot      = test_slot;
            feature_timestamp_ns = test_timestamp;
            trend                = test_trend;
            quantity_imbalance   = test_imbalance;
            spread               = test_spread;
        end
    endtask

    task automatic check_result (
        input logic [1:0]         expected_signal,
        input logic [2:0]         expected_slot,
        input logic [63:0]        expected_timestamp,
        input logic signed [63:0] expected_direction_score,
        input logic signed [63:0] expected_required_score
    );
        begin
            if (signal_valid !== 1'b1) begin
                $fatal(1, "FAIL: signal_valid was not asserted");
            end

            if (trade_signal !== expected_signal) begin
                $fatal(
                    1,
                    "FAIL: expected signal %b, received %b",
                    expected_signal,
                    trade_signal
                );
            end

            if (signal_instrument_slot !== expected_slot) begin
                $fatal(
                    1,
                    "FAIL: expected slot %0d, received %0d",
                    expected_slot,
                    signal_instrument_slot
                );
            end

            if (signal_timestamp_ns !== expected_timestamp) begin
                $fatal(
                    1,
                    "FAIL: expected timestamp %0d, received %0d",
                    expected_timestamp,
                    signal_timestamp_ns
                );
            end

            if (direction_score !== expected_direction_score) begin
                $fatal(
                    1,
                    "FAIL: expected direction score %0d, received %0d",
                    expected_direction_score,
                    $signed(direction_score)
                );
            end

            if (required_score !== expected_required_score) begin
                $fatal(
                    1,
                    "FAIL: expected required score %0d, received %0d",
                    expected_required_score,
                    $signed(required_score)
                );
            end

            $display(
                "PASS: slot=%0d timestamp=%0d signal=%b score=%0d threshold=%0d",
                signal_instrument_slot,
                signal_timestamp_ns,
                trade_signal,
                $signed(direction_score),
                $signed(required_score)
            );
        end
    endtask

    initial begin
        resetn               = 1'b0;
        feature_valid        = 1'b0;
        instrument_slot      = '0;
        feature_timestamp_ns = '0;
        trend                = '0;
        quantity_imbalance   = '0;
        spread               = '0;

        // Apply synchronous reset for two clocks.
        repeat (2) @(posedge clk);

        @(negedge clk);
        resetn = 1'b1;

        // BUY:
        // direction = (50 * 4) + (20 * 1) = 220
        // threshold = 100 + (10 * 2) = 120
        send_feature(
            3'd0,
            64'd1000,
            34'sd50,
            33'sd20,
            32'd10
        );

        // SELL:
        // direction = (-50 * 4) + (-20 * 1) = -220
        // threshold = 100 + (10 * 2) = 120
        send_feature(
            3'd1,
            64'd2000,
            -34'sd50,
            -33'sd20,
            32'd10
        );

        // HOLD:
        // direction = (10 * 4) + (10 * 1) = 50
        // threshold = 100 + (10 * 2) = 120
        send_feature(
            3'd2,
            64'd3000,
            34'sd10,
            33'sd10,
            32'd10
        );

        // Stop sending new features.
        @(negedge clk);
        feature_valid = 1'b0;

        // First result: BUY.
        check_result(
            SIGNAL_BUY,
            3'd0,
            64'd1000,
            64'sd220,
            64'sd120
        );

        // Second result: SELL.
        @(negedge clk);
        check_result(
            SIGNAL_SELL,
            3'd1,
            64'd2000,
            -64'sd220,
            64'sd120
        );

        // Third result: HOLD.
        @(negedge clk);
        check_result(
            SIGNAL_HOLD,
            3'd2,
            64'd3000,
            64'sd50,
            64'sd120
        );

        // Verify that signal_valid clears after the pipeline drains.
        @(negedge clk);

        if (signal_valid !== 1'b0) begin
            $fatal(1, "FAIL: signal_valid did not clear");
        end

        $display("All weighted_decision tests passed.");
        $finish;
    end

    // Stop the simulation if the expected completion is never reached.
    initial begin
        #1000;
        $fatal(1, "FAIL: simulation timeout");
    end

endmodule
```

#### What each testbench section does

**Clock generation**

The clock changes state every 5 ns, producing a 10 ns period and a 100 MHz
simulation clock.

**`send_feature` task**

This task applies one feature set on a falling edge. The values are therefore
stable before the DUT samples them on the following rising edge. Calling the
task three times consecutively creates three back-to-back valid transactions.

**`check_result` task**

This task checks `signal_valid`, the encoded trading decision, the instrument
slot, timestamp, directional score, and required score. A mismatch immediately
ends the simulation using `$fatal`. A correct result prints a `PASS` line.

**BUY test**

The first transaction uses:

$$
(50 \times 4) + (20 \times 1) = 220
$$

The spread-adjusted threshold is:

$$
100 + (10 \times 2) = 120
$$

Since 220 is greater than 120, the expected result is `BUY`.

**SELL test**

The second transaction produces:

$$
(-50 \times 4) + (-20 \times 1) = -220
$$

Since -220 is less than -120, the expected result is `SELL`.

**HOLD test**

The third transaction produces:

$$
(10 \times 4) + (10 \times 1) = 50
$$

The score lies between -120 and 120, so the expected result is `HOLD`.

**Pipeline-drain check**

After all three results have appeared, the testbench checks that
`signal_valid` returns low. This confirms that the valid pipeline does not
produce an extra transaction.

**Timeout**

The independent timeout block prevents the simulation from running forever if
the DUT or testbench fails to reach `$finish`.

---

### Simulation waveform

![Phase 5.1 weighted-decision pipeline waveform](images/phase5_1_weighted_decision_waveform.png)

**Figure 5.1.1 — Three back-to-back feature sets and their pipelined decisions.**

The waveform shows `feature_valid` asserted for three consecutive input cycles.
After the three-stage pipeline fills, `signal_valid` is asserted for three
consecutive output cycles.

The output transactions remain correctly aligned:

| Slot | Timestamp | Direction score | Required score | Decision |
| ---: | ---: | ---: | ---: | --- |
| 0 | 1000 | 220 (`0xDC`) | 120 (`0x78`) | `BUY` (`01`) |
| 1 | 2000 | -220 (`...FF24`) | 120 (`0x78`) | `SELL` (`10`) |
| 2 | 3000 | 50 (`0x32`) | 120 (`0x78`) | `HOLD` (`00`) |

Because the transactions are back-to-back, `signal_valid` appears as one
continuous three-cycle-high interval. Each rising clock while it is high
represents a different valid decision.

The unknown values visible before the first reset clock edge are expected
because the DUT uses synchronous reset. All registers become defined on the
first rising edge for which `resetn` is low.

---

### TCL console result

The complete self-checking simulation was executed with:

```tcl
restart
run all
```

The simulator reported:

```text
INFO: [Wavedata 42-604] Simulation restarted
run all
PASS: slot=0 timestamp=1000 signal=01 score=220 threshold=120
PASS: slot=1 timestamp=2000 signal=10 score=-220 threshold=120
PASS: slot=2 timestamp=3000 signal=00 score=50 threshold=120
All weighted_decision tests passed.
$finish called at time : 90 ns : File "C:/root_pqnq/PYNQ_HFT/PYNQ_HFT.srcs/sim_1/new/weighted_decision_tb.sv" Line 229
```

All three directed cases passed without an arithmetic, control, or metadata
alignment error.

---

### Phase 5.1 result

Phase 5.1 successfully implemented and verified a configurable three-stage
weighted trading-decision pipeline.

The verified block:

- Accepts signed trend and quantity-imbalance features.
- Applies configurable feature weights.
- Raises the trading threshold as the spread increases.
- Generates correctly encoded `BUY`, `SELL`, and `HOLD` decisions.
- Preserves the instrument slot and timestamp through the pipeline.
- Accepts back-to-back feature sets.
- Produces one decision per clock after the pipeline fills.
- Passes all directed self-checking simulation cases.

The next subphase will provide validated, per-instrument market state to the
feature-generation pipeline that eventually drives this decision block.
