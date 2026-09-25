import socket
import struct
import time

#receive packets from all IPs
LISTEN_IP = "0.0.0.0"
LISTEN_PORT = 5001 #at port 5001

#default unique indentifier/magic for every valid packet and version 1
MAGIC = b"HFT1"
VERSION = 1

#same as sender -> allows for receiver to know which packet is start, main loop or end packet 
MESSAGE_QUOTE = 1
CONTROL_START = 254
CONTROL_END = 255

#32 byte packet of defined structure 
PACKET_STRUCT = struct.Struct("!4sBBBBIQIII")
PACKET_SIZE = PACKET_STRUCT.size

#sender buffer was 4Mib and so is receiver buffer bytes -> tbh very overkill given the packet rates run at but that was unknown at the time of creating this code 
RECEIVE_BUFFER_BYTES = 4 * 1024 * 1024
MAX_DATAGRAM_SIZE = 2_048
MAX_PLANNED_PACKETS = 10_000_000
INACTIVITY_TIMEOUT_SECONDS = 2.0
MIN_RATE_FRACTION = 0.995


class StreamTest:
    #setup inactive, empty test
    def __init__(self):
        self.active = False #no stream test currently running since its just being set up 

        #params that describe the test
        self.sender = None
        self.target_rate = 0
        self.target_duration = 0.0
        self.planned_packets = 0
        self.seen = None #track which sequence numbers have arrived
        
        #store number of valid packets and categories error packets depending on their type 
        self.valid_packets = 0
        self.invalid_packets = 0
        self.duplicate_packets = 0
        self.out_of_order_packets = 0
        self.highest_sequence = 0

        #setting up test so set all to None/0
        self.first_packet_time = None
        self.last_report_time = None
        self.last_report_valid = 0
        self.last_activity_time = None

    #start test 
    def start(self, sender, target_rate, duration_ms, planned_packets, now):
        self.active = True
        self.sender = sender
        self.target_rate = target_rate
        self.target_duration = duration_ms / 1_000.0
        self.planned_packets = planned_packets
        self.seen = bytearray(planned_packets + 1) #in sender code the quote packets start at sequence 1
        #so seen[0] is unused and seen[1 -> 75000] are used 

        #packet stats still 0 since nothing actually sent yet
        self.valid_packets = 0
        self.invalid_packets = 0
        self.duplicate_packets = 0
        self.out_of_order_packets = 0
        self.highest_sequence = 0

        self.first_packet_time = None
        self.last_report_time = None
        self.last_report_valid = 0
        self.last_activity_time = now

        print("\nStream test started")
        print(f"Sender:          {sender}")
        print(f"Target rate:     {target_rate:,} packets/s")
        print(f"Test duration:   {self.target_duration:.3f} seconds")
        print(f"Planned packets: {planned_packets:,}")

    #record each packet
    def record_valid_packet(self, sequence, now):
        #first packet sent so record its timestamp
        if self.first_packet_time is None:
            self.first_packet_time = now
            self.last_report_time = now
            self.last_report_valid = 0

        #sequence in [1, 75000] so if seen[x] is something, the same packet has alr been received
        #so its a dupe
        if self.seen[sequence]:
            self.duplicate_packets += 1
            self.last_activity_time = now
            return

        #record that particular packet with sequence number has been seen to check for duplicates later
        self.seen[sequence] = 1

        # packets should arrive with sequences that are 1 larger than the previous
        #so if a smaller sequence is seen than the current maximum at the receiver, 
        #packets have been sent in incorrect order
        if sequence < self.highest_sequence:
            self.out_of_order_packets += 1

        #normal behaviour -> set new highest sequence to current sequence
        if sequence > self.highest_sequence:
            self.highest_sequence = sequence

        # if no execption returns, packet is valid and the current packet's timestamp is now stored
        self.valid_packets += 1
        self.last_activity_time = now

        #current report time - previous report time > 1s recalculate the packet rate 
        #i.e output packet rate in that given second
        report_elapsed = now - self.last_report_time

        if report_elapsed >= 1.0:
            interval_packets = self.valid_packets - self.last_report_valid
            interval_rate = interval_packets / report_elapsed

            print(
                f"Valid: {self.valid_packets:,} | "
                f"Invalid: {self.invalid_packets:,} | "
                f"Duplicates: {self.duplicate_packets:,} | "
                f"Out of order: {self.out_of_order_packets:,} | "
                f"Rate: {interval_rate:,.0f} pps"
            )
                
            self.last_report_time = now #make this the new start of the "next second" (not exactly but close enough)
            self.last_report_valid = self.valid_packets

    def record_invalid_packet(self, now): #call when invalid packet seen
        self.invalid_packets += 1
        self.last_activity_time = now
    #take counters collected during test and calculate final rates and print out test report 
    def finish(self, end_time, packets_sent=None, timed_out=False):
        #check whether a test is running -> only if not should we actually call this 
        if not self.active:
            return

        #no endmarker, packets_sent will have no value so we assign it the planned rate value
        if packets_sent is None:
            packets_sent = self.planned_packets

        #recalculate packets sent and calculate missing packets. Saturate packets sent at the minimum
        # of packets_sent and planned_packets
        packets_sent = max(0, min(packets_sent, self.planned_packets))
        missing_packets = max(0, packets_sent - self.valid_packets)

        #calculate packet rate basically valid packets / (end_time - start_time)
        if self.first_packet_time is None:
            measured_duration = 0.0
            average_rate = 0.0
        else:
            measured_duration = end_time - self.first_packet_time
            average_rate = (
                self.valid_packets / measured_duration
                if measured_duration > 0
                else 0.0
            )

        # convert to erroneous packet rates specific type of packet malformation
        if packets_sent > 0:
            packet_error_rate = 100.0 * missing_packets / packets_sent
            invalid_rate = 100.0 * self.invalid_packets / packets_sent
            duplicate_rate = 100.0 * self.duplicate_packets / packets_sent
            out_of_order_rate = (
                100.0 * self.out_of_order_packets / packets_sent
            )
        else:
            packet_error_rate = 0.0
            invalid_rate = 0.0
            duplicate_rate = 0.0
            out_of_order_rate = 0.0

        #no erroneous packets received so all packets received were valid
        integrity_ok = (
            packets_sent == self.planned_packets
            and missing_packets == 0
            and self.invalid_packets == 0
            and self.duplicate_packets == 0
            and self.out_of_order_packets == 0
        )
        #rate is fine if it exceeds target rate
        # and the test passes if integrity and rate are both what they should be (0 errors and target rate)
        rate_ok = average_rate >= self.target_rate * MIN_RATE_FRACTION
        result = "PASS" if integrity_ok and rate_ok else "FAIL"

        print("\nStream test complete")
        if timed_out:
            print("Warning: end marker was not received; report used inactivity timeout")
        print(f"Target rate:           {self.target_rate:,} packets/s")
        print(f"Packets sent:          {packets_sent:,}")
        print(f"Valid unique packets:  {self.valid_packets:,}")
        print(f"Missing packets:       {missing_packets:,}")
        print(f"Invalid packets:       {self.invalid_packets:,}")
        print(f"Duplicate packets:     {self.duplicate_packets:,}")
        print(f"Out-of-order packets:  {self.out_of_order_packets:,}")
        print(f"Highest sequence:      {self.highest_sequence:,}")
        print(f"Measured duration:     {measured_duration:.3f} s")
        print(f"Average receive rate:  {average_rate:,.0f} pps")
        print(f"Packet error rate:     {packet_error_rate:.6f}%")
        print(f"Invalid packet rate:   {invalid_rate:.6f}%")
        print(f"Duplicate packet rate: {duplicate_rate:.6f}%")
        print(f"Out-of-order rate:     {out_of_order_rate:.6f}%")
        print(f"Real-time rate check:  {'PASS' if rate_ok else 'FAIL'}")
        print(f"Result:                {result}")

        #stop test and release sequence array 
        self.active = False
        self.sender = None
        self.seen = None


#ensure target rate, test duration and total planned packets all within acceptable range
def valid_start_control(target_rate, duration_ms, planned_packets):
    return (
        target_rate > 0
        and duration_ms > 0
        and 0 < planned_packets <= MAX_PLANNED_PACKETS
    )


def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM) #create receiver socket
    sock.setsockopt(
        socket.SOL_SOCKET,
        socket.SO_RCVBUF,
        RECEIVE_BUFFER_BYTES,
    ) #increase buffer 
    sock.bind((LISTEN_IP, LISTEN_PORT)) # bind socket at sender IP and port 5001
    sock.settimeout(0.5) #receive call can wait up to 0.5s for a datagram before raising a timeout

    #OS may report different size of receive buffer that is not 4MiB -> used only for print status line
    actual_buffer = sock.getsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF)

    #2048 byte python array 
    #for normal packet only 32 bytes are used 
    receive_buffer = bytearray(MAX_DATAGRAM_SIZE)
    
    #create object that holds test state (__init__() runs now)
    test = StreamTest()

    print(f"Listening for {PACKET_SIZE}-byte market packets...")
    print(f"UDP port: {LISTEN_PORT}")
    print(f"UDP receive buffer: {actual_buffer:,} bytes")

    try:
        while True:
            try:
                #wait for datagram
                #recvfrom_into writes datagram into the reusble 2048 byte array
                received_bytes, sender = sock.recvfrom_into(receive_buffer)
                now = time.perf_counter()

            #if no datagram is received in 0.5s period, socket times out 
            except socket.timeout:
                now = time.perf_counter()

                #if theres an active test with a an activity time and atleast 2s has passed
                #since activity it calls the finish function 
                if (
                    test.active
                    and test.last_activity_time is not None
                    and now - test.last_activity_time
                    >= INACTIVITY_TIMEOUT_SECONDS
                ):
                    test.finish(test.last_activity_time, timed_out=True)

                continue

            #number of bytes in received packet is not 32 so record the invalid packet
            #incrment invalid packet count by 1
            if received_bytes != PACKET_SIZE:
                if test.active:
                    test.record_invalid_packet(now)
                continue

            #packet byte allocation predifined 
            #struct.Struct("!4sBBBBIQIII")
            #so unpack fields from receive packet 
            (
                magic,
                version,
                message_type,
                side,
                flags,
                sequence,
                timestamp_ns,
                instrument_id,
                price_ticks,
                quantity,
            ) = PACKET_STRUCT.unpack_from(receive_buffer)

            #unique identifier and version must match else its an invalid packet
            if magic != MAGIC or version != VERSION:
                if test.active:
                    test.record_invalid_packet(now)
                continue

            #start packet recorded -> target rate, duration and planned packets can be extracted
            #see sender code
            if message_type == CONTROL_START:
                target_rate = instrument_id
                duration_ms = price_ticks
                planned_packets = quantity

                #start test if the test parameters are in valid range ( > 0 and not exceeding total 
                #packet count
                if valid_start_control(
                    target_rate,
                    duration_ms,
                    planned_packets,
                ):
                    test.start(
                        sender,
                        target_rate,
                        duration_ms,
                        planned_packets,
                        now,
                    )
                continue

            #end packet received test elapsed so calculate results using finish 
            if message_type == CONTROL_END:
                if test.active and sender == test.sender:
                    test.last_activity_time = now
                    test.finish(now, packets_sent=quantity)
                continue

            if not test.active:
                continue

            if sender != test.sender:
                test.record_invalid_packet(now)
                continue

            #record invalid packet -> side has to be BUY (0) or sell (1) 
            #message type if not a start or an end packet has to match message quote
            #sequence needs to be between 1 and planned packets 
            if (
                message_type != MESSAGE_QUOTE
                or side not in (0, 1)
                or not 1 <= sequence <= test.planned_packets
            ):
                test.record_invalid_packet(now)
                continue
            #if all tests pass packet is considered valid, so record it and 
            #increment valid packet 
            test.record_valid_packet(sequence, now)

    except KeyboardInterrupt:
        print("\nReceiver stopped")

    #close socket after test elapsed and results output 
    finally:
        sock.close()


if __name__ == "__main__":
    main()
