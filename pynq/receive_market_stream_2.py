import socket
import struct
import time


LISTEN_IP = "0.0.0.0"
LISTEN_PORT = 5001

MAGIC = b"HFT1"
VERSION = 1

MESSAGE_QUOTE = 1
CONTROL_START = 254
CONTROL_END = 255

PACKET_STRUCT = struct.Struct("!4sBBBBIQIII")
PACKET_SIZE = PACKET_STRUCT.size

RECEIVE_BUFFER_BYTES = 4 * 1024 * 1024
MAX_DATAGRAM_SIZE = 2_048
MAX_PLANNED_PACKETS = 10_000_000
INACTIVITY_TIMEOUT_SECONDS = 2.0
MIN_RATE_FRACTION = 0.995


class StreamTest:
    def __init__(self):
        self.active = False
        self.sender = None
        self.target_rate = 0
        self.target_duration = 0.0
        self.planned_packets = 0
        self.seen = None

        self.valid_packets = 0
        self.invalid_packets = 0
        self.duplicate_packets = 0
        self.out_of_order_packets = 0
        self.highest_sequence = 0

        self.first_packet_time = None
        self.last_report_time = None
        self.last_report_valid = 0
        self.last_activity_time = None

    def start(self, sender, target_rate, duration_ms, planned_packets, now):
        self.active = True
        self.sender = sender
        self.target_rate = target_rate
        self.target_duration = duration_ms / 1_000.0
        self.planned_packets = planned_packets
        self.seen = bytearray(planned_packets + 1)

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

    def record_valid_packet(self, sequence, now):
        if self.first_packet_time is None:
            self.first_packet_time = now
            self.last_report_time = now
            self.last_report_valid = 0

        if self.seen[sequence]:
            self.duplicate_packets += 1
            self.last_activity_time = now
            return

        self.seen[sequence] = 1

        if sequence < self.highest_sequence:
            self.out_of_order_packets += 1

        if sequence > self.highest_sequence:
            self.highest_sequence = sequence

        self.valid_packets += 1
        self.last_activity_time = now

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

            self.last_report_time = now
            self.last_report_valid = self.valid_packets

    def record_invalid_packet(self, now):
        self.invalid_packets += 1
        self.last_activity_time = now

    def finish(self, end_time, packets_sent=None, timed_out=False):
        if not self.active:
            return

        if packets_sent is None:
            packets_sent = self.planned_packets

        packets_sent = max(0, min(packets_sent, self.planned_packets))
        missing_packets = max(0, packets_sent - self.valid_packets)

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

        integrity_ok = (
            packets_sent == self.planned_packets
            and missing_packets == 0
            and self.invalid_packets == 0
            and self.duplicate_packets == 0
            and self.out_of_order_packets == 0
        )
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

        self.active = False
        self.sender = None
        self.seen = None


def valid_start_control(target_rate, duration_ms, planned_packets):
    return (
        target_rate > 0
        and duration_ms > 0
        and 0 < planned_packets <= MAX_PLANNED_PACKETS
    )


def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(
        socket.SOL_SOCKET,
        socket.SO_RCVBUF,
        RECEIVE_BUFFER_BYTES,
    )
    sock.bind((LISTEN_IP, LISTEN_PORT))
    sock.settimeout(0.5)

    actual_buffer = sock.getsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF)
    receive_buffer = bytearray(MAX_DATAGRAM_SIZE)
    test = StreamTest()

    print(f"Listening for {PACKET_SIZE}-byte market packets...")
    print(f"UDP port: {LISTEN_PORT}")
    print(f"UDP receive buffer: {actual_buffer:,} bytes")

    try:
        while True:
            try:
                received_bytes, sender = sock.recvfrom_into(receive_buffer)
                now = time.perf_counter()

            except socket.timeout:
                now = time.perf_counter()

                if (
                    test.active
                    and test.last_activity_time is not None
                    and now - test.last_activity_time
                    >= INACTIVITY_TIMEOUT_SECONDS
                ):
                    test.finish(test.last_activity_time, timed_out=True)

                continue

            if received_bytes != PACKET_SIZE:
                if test.active:
                    test.record_invalid_packet(now)
                continue

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

            if magic != MAGIC or version != VERSION:
                if test.active:
                    test.record_invalid_packet(now)
                continue

            if message_type == CONTROL_START:
                target_rate = instrument_id
                duration_ms = price_ticks
                planned_packets = quantity

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

            if (
                message_type != MESSAGE_QUOTE
                or side not in (0, 1)
                or not 1 <= sequence <= test.planned_packets
            ):
                test.record_invalid_packet(now)
                continue

            test.record_valid_packet(sequence, now)

    except KeyboardInterrupt:
        print("\nReceiver stopped")

    finally:
        sock.close()


if __name__ == "__main__":
    main()
