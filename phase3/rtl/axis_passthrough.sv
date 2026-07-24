// receives AXI4-stream word from MM2S DMA then stores it and forwards it to S2MM DMA
module axis_passthrough#(
    parameter DATA_WIDTH = 32 // width of each word - set to default rn 
    )(
    input logic aclk, // logic changes on rising edge 
    input logic aresetn, //active low reset signal; clear output register when brought low 
    
    input logic [DATA_WIDTH-1:0] s_axis_tdata, // 32 bit word presentred by DMA; contains one 32 bit packet word 
    input logic s_axis_tvalid, // Brought high BY DMA when s_axis contains valid data
    output logic s_axis_tready, // asserted by module when it can accept a 32 bit input (handshake value)
    input logic s_axis_tlast, // Brought high bY DMA when current input  is the final word of DMA packet
    
    output logic [DATA_WIDTH-1:0] m_axis_tdata, // word presented by module to S2MM DMA (Stream 2 Mem Mapped DMA)
    output logic m_axis_tvalid, // brought high when m_axis_tdata is valid 
    input logic m_axis_tready, // brought high by Stream to Mem Mapped  DMA when it can accept output word
    output logic m_axis_tlast  // brought high when m_axis_tdata is the final word of transfer
    );
    
    // found this part a bit confusing myself when learning AXI so im adding an explanation here
    
    // The module can accept a new input word when EITHER
    
    // The output register is empty (!m_axis_tvalid), so there is
    // free space to store the new word, regardless of whether
    // S2MM is currently ready.
    
    // OR 
    
    // 2. The output register contains valid data, but S2MM is ready
    // to accept it (m_axis_tready). The old word will leave and
    // can be replaced by a new word on the same rising clock edge.
    
    // Input is blocked only when the output register is full and
    // S2MM is not ready, because accepting new data would overwrite
    // the currently stored word.
    assign s_axis_tready = !m_axis_tvalid || m_axis_tready; //ready when output register is empty OR begin drained 
    
    always_ff @ (posedge aclk) begin 
        // clear stored output data when reset called 
        if (!aresetn) begin 
            m_axis_tdata <= '0;
            m_axis_tvalid <= 1'b0;
            m_axis_tlast <= 1'b0;
        end 
        
        // Block only runs when input side is ready (s_axis_tready = 1)
        else if (s_axis_tready) begin 
            m_axis_tvalid <= s_axis_tvalid; //tell S2MM DMA that word currently input to module is valid 
            // here, m_axis_treadt can be low as information is being provided to S2MM DMA about the validity
            // of data from M2SS DMA 
            
            // Only load data when when M2SS DMA is presenting non bogus input word 
            if (s_axis_tvalid) begin
                m_axis_tdata <= s_axis_tdata; 
                // Store the valid input word in the output register.
                    // S2MM might not be ready yet; the word is held until
                    // m_axis_tvalid && m_axis_tready are both high.
                    
                m_axis_tlast <= s_axis_tlast; // tells S2MM DMA when M2SS DMA has sent the last word to this module and 
                // hence should expect it to be the last when it m_axis_tlast goes high (1 cycle later than s_axis_tlast) 
            end 
        end     
    end 
endmodule
