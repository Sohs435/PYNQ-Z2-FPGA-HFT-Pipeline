#define _GNU_SOURCE

#include <arpa/inet.h>
#include <errno.h>
#include <getopt.h>
#include <inttypes.h>
#include <netinet/in.h>
#include <signal.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/resource.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>


#define DEFAULT_LISTEN_IP "0.0.0.0"
#define DEFAULT_LISTEN_PORT 5001
#define DEFAULT_BATCH_SIZE 64
#define MAX_BATCH_SIZE 256

#define PACKET_SIZE 32
#define MAX_DATAGRAM_SIZE 2048
#define RECEIVE_BUFFER_BYTES (4 * 1024 * 1024)
#define MAX_PLANNED_PACKETS 10000000U
#define REPORT_CHECK_PACKETS 1024U
#define MIN_RATE_FRACTION 0.995

#define MESSAGE_QUOTE_UPDATE 1
#define MESSAGE_STREAM_START 4
#define MESSAGE_STREAM_END 5
#define SUPPORTED_VERSION 1


static volatile sig_atomic_t stop_requested = 0;


struct udp_statistics {
    uint64_t in_datagrams;
    uint64_t no_ports;
    uint64_t in_errors;
    uint64_t out_datagrams;
    uint64_t rcvbuf_errors;
    uint64_t sndbuf_errors;
    bool valid;
};


struct stream_state {
    bool active;
    struct sockaddr_in sender;

    uint32_t target_pps;
    uint32_t planned_packets;
    uint8_t *seen_sequences;

    uint64_t valid_packets;
    uint64_t invalid_packets;
    uint64_t duplicate_packets;
    uint64_t out_of_order_packets;
    uint32_t highest_sequence;

    bool first_packet_seen;
    struct timespec first_packet_time;
    struct timespec last_report_time;
    uint64_t packets_at_last_report;
    uint64_t next_report_check;

    uint64_t recvmmsg_calls;
    uint64_t messages_returned;
    unsigned int maximum_batch_returned;

    struct udp_statistics udp_start;
    struct rusage cpu_start;
};


static void handle_signal(int signal_number)
{
    (void)signal_number;
    stop_requested = 1;
}


static uint32_t load_be32(const uint8_t *source)
{
    uint32_t value;
    memcpy(&value, source, sizeof(value));
    return ntohl(value);
}


static double timespec_difference(
    const struct timespec *end,
    const struct timespec *start)
{
    return (double)(end->tv_sec - start->tv_sec)
        + (double)(end->tv_nsec - start->tv_nsec) / 1000000000.0;
}


static bool same_sender(
    const struct sockaddr_in *first,
    const struct sockaddr_in *second)
{
    return first->sin_family == second->sin_family
        && first->sin_port == second->sin_port
        && first->sin_addr.s_addr == second->sin_addr.s_addr;
}


static struct udp_statistics read_udp_statistics(void)
{
    struct udp_statistics statistics = {0};
    FILE *file = fopen("/proc/net/snmp", "r");
    char header[1024];
    char values[1024];

    if (file == NULL) {
        return statistics;
    }

    while (fgets(header, sizeof(header), file) != NULL) {
        if (strncmp(header, "Udp:", 4) != 0) {
            continue;
        }

        if (fgets(values, sizeof(values), file) == NULL) {
            break;
        }

        if (sscanf(
                values,
                "Udp: %" SCNu64 " %" SCNu64 " %" SCNu64
                " %" SCNu64 " %" SCNu64 " %" SCNu64,
                &statistics.in_datagrams,
                &statistics.no_ports,
                &statistics.in_errors,
                &statistics.out_datagrams,
                &statistics.rcvbuf_errors,
                &statistics.sndbuf_errors) == 6) {
            statistics.valid = true;
        }

        break;
    }

    fclose(file);
    return statistics;
}


static void reset_stream(
    struct stream_state *state,
    const struct sockaddr_in *sender,
    uint32_t target_pps,
    uint32_t planned_packets)
{
    free(state->seen_sequences);
    state->seen_sequences = calloc((size_t)planned_packets + 1U, 1U);

    if (state->seen_sequences == NULL) {
        fprintf(stderr, "Unable to allocate sequence bitmap\n");
        exit(EXIT_FAILURE);
    }

    state->active = true;
    state->sender = *sender;
    state->target_pps = target_pps;
    state->planned_packets = planned_packets;

    state->valid_packets = 0;
    state->invalid_packets = 0;
    state->duplicate_packets = 0;
    state->out_of_order_packets = 0;
    state->highest_sequence = 0;

    state->first_packet_seen = false;
    memset(&state->first_packet_time, 0, sizeof(state->first_packet_time));
    memset(&state->last_report_time, 0, sizeof(state->last_report_time));
    state->packets_at_last_report = 0;
    state->next_report_check = REPORT_CHECK_PACKETS;

    state->recvmmsg_calls = 0;
    state->messages_returned = 0;
    state->maximum_batch_returned = 0;

    state->udp_start = read_udp_statistics();
    getrusage(RUSAGE_SELF, &state->cpu_start);
}


static void print_stream_start(
    const struct stream_state *state,
    uint32_t duration_ms)
{
    char sender_ip[INET_ADDRSTRLEN];
    const char *address = inet_ntop(
        AF_INET,
        &state->sender.sin_addr,
        sender_ip,
        sizeof(sender_ip));

    if (address == NULL) {
        address = "unknown";
    }

    printf("\nStream test started\n");
    printf(
        "Sender:          %s:%u\n",
        address,
        (unsigned int)ntohs(state->sender.sin_port));
    printf("Target rate:     %" PRIu32 " packets/s\n", state->target_pps);
    printf("Test duration:   %.3f seconds\n", duration_ms / 1000.0);
    printf("Planned packets: %" PRIu32 "\n", state->planned_packets);
}


static void print_periodic_report(
    struct stream_state *state,
    const struct timespec *now)
{
    double elapsed = timespec_difference(now, &state->last_report_time);

    if (elapsed < 1.0) {
        return;
    }

    uint64_t interval_packets =
        state->valid_packets - state->packets_at_last_report;
    double interval_rate = interval_packets / elapsed;

    printf(
        "Valid: %" PRIu64 " | Invalid: %" PRIu64
        " | Duplicates: %" PRIu64 " | Out of order: %" PRIu64
        " | Rate: %.0f pps\n",
        state->valid_packets,
        state->invalid_packets,
        state->duplicate_packets,
        state->out_of_order_packets,
        interval_rate);

    state->last_report_time = *now;
    state->packets_at_last_report = state->valid_packets;
}


static void finish_stream(
    struct stream_state *state,
    uint32_t sequence,
    uint32_t quantity)
{
    struct timespec end_time;
    struct rusage cpu_end;
    struct udp_statistics udp_end;
    uint32_t actual_sent = quantity;

    if (actual_sent < 1 || actual_sent > state->planned_packets) {
        actual_sent = sequence;
    }
    if (actual_sent < 1 || actual_sent > state->planned_packets) {
        actual_sent = state->planned_packets;
    }

    clock_gettime(CLOCK_MONOTONIC, &end_time);
    getrusage(RUSAGE_SELF, &cpu_end);
    udp_end = read_udp_statistics();

    uint64_t missing_packets = actual_sent > state->valid_packets
        ? actual_sent - state->valid_packets
        : 0;

    double measured_duration = state->first_packet_seen
        ? timespec_difference(&end_time, &state->first_packet_time)
        : 0.0;
    double average_receive_pps = measured_duration > 0.0
        ? state->valid_packets / measured_duration
        : 0.0;

    double packet_error_rate = actual_sent > 0
        ? 100.0 * missing_packets / actual_sent
        : 0.0;
    double invalid_rate = actual_sent > 0
        ? 100.0 * state->invalid_packets / actual_sent
        : 0.0;
    double duplicate_rate = actual_sent > 0
        ? 100.0 * state->duplicate_packets / actual_sent
        : 0.0;
    double out_of_order_rate = actual_sent > 0
        ? 100.0 * state->out_of_order_packets / actual_sent
        : 0.0;

    double user_cpu =
        (cpu_end.ru_utime.tv_sec - state->cpu_start.ru_utime.tv_sec)
        + (cpu_end.ru_utime.tv_usec - state->cpu_start.ru_utime.tv_usec)
            / 1000000.0;
    double system_cpu =
        (cpu_end.ru_stime.tv_sec - state->cpu_start.ru_stime.tv_sec)
        + (cpu_end.ru_stime.tv_usec - state->cpu_start.ru_stime.tv_usec)
            / 1000000.0;
    double process_cpu_percent = measured_duration > 0.0
        ? 100.0 * (user_cpu + system_cpu) / measured_duration
        : 0.0;

    double average_batch = state->recvmmsg_calls > 0
        ? (double)state->messages_returned / state->recvmmsg_calls
        : 0.0;

    bool rate_ok =
        average_receive_pps >= state->target_pps * MIN_RATE_FRACTION;
    bool integrity_ok =
        actual_sent == state->planned_packets
        && missing_packets == 0
        && state->invalid_packets == 0
        && state->duplicate_packets == 0
        && state->out_of_order_packets == 0;

    printf("\nStream test complete\n");
    printf("Target rate:             %" PRIu32 " packets/s\n", state->target_pps);
    printf("Packets sent:            %" PRIu32 "\n", actual_sent);
    printf("Valid unique packets:    %" PRIu64 "\n", state->valid_packets);
    printf("Missing packets:         %" PRIu64 "\n", missing_packets);
    printf("Invalid packets:         %" PRIu64 "\n", state->invalid_packets);
    printf("Duplicate packets:       %" PRIu64 "\n", state->duplicate_packets);
    printf("Out-of-order packets:    %" PRIu64 "\n", state->out_of_order_packets);
    printf("Highest sequence:        %" PRIu32 "\n", state->highest_sequence);
    printf("Measured duration:       %.6f s\n", measured_duration);
    printf("Average receive rate:    %.0f pps\n", average_receive_pps);
    printf("Packet error rate:       %.6f%%\n", packet_error_rate);
    printf("Invalid packet rate:     %.6f%%\n", invalid_rate);
    printf("Duplicate packet rate:   %.6f%%\n", duplicate_rate);
    printf("Out-of-order rate:       %.6f%%\n", out_of_order_rate);
    printf("Process user CPU:        %.3f s\n", user_cpu);
    printf("Process system CPU:      %.3f s\n", system_cpu);
    printf("Process CPU utilisation: %.1f%% of one core\n", process_cpu_percent);
    printf("recvmmsg calls:          %" PRIu64 "\n", state->recvmmsg_calls);
    printf("Average receive batch:   %.2f packets/call\n", average_batch);
    printf("Maximum receive batch:   %u packets\n", state->maximum_batch_returned);

    if (state->udp_start.valid && udp_end.valid) {
        printf(
            "Kernel UDP InErrors:     %" PRIu64 "\n",
            udp_end.in_errors - state->udp_start.in_errors);
        printf(
            "Kernel UDP RcvbufErrors: %" PRIu64 "\n",
            udp_end.rcvbuf_errors - state->udp_start.rcvbuf_errors);
    }

    printf("Real-time rate check:    %s\n", rate_ok ? "PASS" : "FAIL");
    printf("Result:                  %s\n", integrity_ok && rate_ok ? "PASS" : "FAIL");

    state->active = false;
    free(state->seen_sequences);
    state->seen_sequences = NULL;
}


static void process_datagram(
    struct stream_state *state,
    const uint8_t *packet,
    unsigned int packet_length,
    const struct sockaddr_in *sender,
    bool periodic_reports)
{
    if (packet_length != PACKET_SIZE) {
        if (state->active) {
            state->invalid_packets++;
        }
        return;
    }

    if (memcmp(packet, "HFT1", 4) != 0 || packet[4] != SUPPORTED_VERSION) {
        if (state->active) {
            state->invalid_packets++;
        }
        return;
    }

    uint8_t message_type = packet[5];
    uint8_t side = packet[6];
    uint8_t flags = packet[7];
    uint32_t sequence = load_be32(packet + 8);

    if (message_type == MESSAGE_STREAM_START) {
        uint32_t target_pps = load_be32(packet + 20);
        uint32_t duration_ms = load_be32(packet + 24);
        uint32_t planned_packets = load_be32(packet + 28);

        if (target_pps < 1
            || duration_ms < 1
            || planned_packets < 1
            || planned_packets > MAX_PLANNED_PACKETS) {
            return;
        }

        reset_stream(state, sender, target_pps, planned_packets);
        print_stream_start(state, duration_ms);
        return;
    }

    if (message_type == MESSAGE_STREAM_END) {
        if (!state->active || !same_sender(sender, &state->sender)) {
            return;
        }

        finish_stream(state, sequence, load_be32(packet + 28));
        return;
    }

    if (!state->active) {
        return;
    }

    if (!same_sender(sender, &state->sender)) {
        state->invalid_packets++;
        return;
    }

    if (message_type != MESSAGE_QUOTE_UPDATE
        || side > 1
        || flags != 0
        || sequence < 1
        || sequence > state->planned_packets) {
        state->invalid_packets++;
        return;
    }

    if (state->seen_sequences[sequence]) {
        state->duplicate_packets++;
        return;
    }

    state->seen_sequences[sequence] = 1;
    state->valid_packets++;

    if (sequence < state->highest_sequence) {
        state->out_of_order_packets++;
    } else if (sequence > state->highest_sequence) {
        state->highest_sequence = sequence;
    }

    if (!state->first_packet_seen) {
        clock_gettime(CLOCK_MONOTONIC, &state->first_packet_time);
        state->last_report_time = state->first_packet_time;
        state->first_packet_seen = true;
    }

    if (periodic_reports && state->valid_packets >= state->next_report_check) {
        struct timespec now;
        clock_gettime(CLOCK_MONOTONIC, &now);
        print_periodic_report(state, &now);
        state->next_report_check =
            state->valid_packets + REPORT_CHECK_PACKETS;
    }
}


static void print_usage(const char *program_name)
{
    printf(
        "Usage: %s [--ip ADDRESS] [--port PORT] [--batch SIZE] [--report]\n",
        program_name);
}


int main(int argc, char **argv)
{
    const char *listen_ip = DEFAULT_LISTEN_IP;
    int listen_port = DEFAULT_LISTEN_PORT;
    int batch_size = DEFAULT_BATCH_SIZE;
    bool periodic_reports = false;

    static const struct option options[] = {
        {"ip", required_argument, NULL, 'i'},
        {"port", required_argument, NULL, 'p'},
        {"batch", required_argument, NULL, 'b'},
        {"report", no_argument, NULL, 'r'},
        {"help", no_argument, NULL, 'h'},
        {NULL, 0, NULL, 0}
    };

    int option;
    while ((option = getopt_long(argc, argv, "i:p:b:rh", options, NULL)) != -1) {
        switch (option) {
        case 'i':
            listen_ip = optarg;
            break;
        case 'p':
            listen_port = atoi(optarg);
            break;
        case 'b':
            batch_size = atoi(optarg);
            break;
        case 'r':
            periodic_reports = true;
            break;
        case 'h':
            print_usage(argv[0]);
            return EXIT_SUCCESS;
        default:
            print_usage(argv[0]);
            return EXIT_FAILURE;
        }
    }

    if (listen_port < 1 || listen_port > 65535) {
        fprintf(stderr, "Port must be between 1 and 65535\n");
        return EXIT_FAILURE;
    }
    if (batch_size < 1 || batch_size > MAX_BATCH_SIZE) {
        fprintf(stderr, "Batch size must be between 1 and %d\n", MAX_BATCH_SIZE);
        return EXIT_FAILURE;
    }

    setvbuf(stdout, NULL, _IOLBF, 0);

    struct sigaction signal_action = {0};
    signal_action.sa_handler = handle_signal;
    sigemptyset(&signal_action.sa_mask);
    signal_action.sa_flags = 0;
    sigaction(SIGINT, &signal_action, NULL);
    sigaction(SIGTERM, &signal_action, NULL);

    int socket_fd = socket(AF_INET, SOCK_DGRAM, 0);
    if (socket_fd < 0) {
        perror("socket");
        return EXIT_FAILURE;
    }

    int reuse_address = 1;
    setsockopt(
        socket_fd,
        SOL_SOCKET,
        SO_REUSEADDR,
        &reuse_address,
        sizeof(reuse_address));

    int requested_buffer = RECEIVE_BUFFER_BYTES;
    if (setsockopt(
            socket_fd,
            SOL_SOCKET,
            SO_RCVBUF,
            &requested_buffer,
            sizeof(requested_buffer)) < 0) {
        perror("setsockopt SO_RCVBUF");
        close(socket_fd);
        return EXIT_FAILURE;
    }

    struct sockaddr_in listen_address = {0};
    listen_address.sin_family = AF_INET;
    listen_address.sin_port = htons((uint16_t)listen_port);

    if (inet_pton(AF_INET, listen_ip, &listen_address.sin_addr) != 1) {
        fprintf(stderr, "Invalid IPv4 listen address: %s\n", listen_ip);
        close(socket_fd);
        return EXIT_FAILURE;
    }

    if (bind(
            socket_fd,
            (struct sockaddr *)&listen_address,
            sizeof(listen_address)) < 0) {
        perror("bind");
        close(socket_fd);
        return EXIT_FAILURE;
    }

    int actual_buffer = 0;
    socklen_t actual_buffer_length = sizeof(actual_buffer);
    getsockopt(
        socket_fd,
        SOL_SOCKET,
        SO_RCVBUF,
        &actual_buffer,
        &actual_buffer_length);

    struct mmsghdr *messages = calloc((size_t)batch_size, sizeof(*messages));
    struct iovec *vectors = calloc((size_t)batch_size, sizeof(*vectors));
    struct sockaddr_in *senders = calloc((size_t)batch_size, sizeof(*senders));
    uint8_t *buffers = calloc(
        (size_t)batch_size,
        (size_t)MAX_DATAGRAM_SIZE);

    if (messages == NULL || vectors == NULL || senders == NULL || buffers == NULL) {
        fprintf(stderr, "Unable to allocate receive batch\n");
        free(messages);
        free(vectors);
        free(senders);
        free(buffers);
        close(socket_fd);
        return EXIT_FAILURE;
    }

    for (int index = 0; index < batch_size; index++) {
        vectors[index].iov_base =
            buffers + (size_t)index * MAX_DATAGRAM_SIZE;
        vectors[index].iov_len = MAX_DATAGRAM_SIZE;
        messages[index].msg_hdr.msg_name = &senders[index];
        messages[index].msg_hdr.msg_namelen = sizeof(senders[index]);
        messages[index].msg_hdr.msg_iov = &vectors[index];
        messages[index].msg_hdr.msg_iovlen = 1;
    }

    struct stream_state state = {0};

    printf("Listening for %d-byte market packets...\n", PACKET_SIZE);
    printf("UDP port:           %d\n", listen_port);
    printf("UDP receive buffer: %d bytes\n", actual_buffer);
    printf("recvmmsg batch size: %d\n", batch_size);
    printf("Periodic reports:   %s\n", periodic_reports ? "enabled" : "disabled");

    while (!stop_requested) {
        for (int index = 0; index < batch_size; index++) {
            messages[index].msg_len = 0;
            messages[index].msg_hdr.msg_namelen = sizeof(senders[index]);
            messages[index].msg_hdr.msg_flags = 0;
        }

        bool call_started_active = state.active;
        int received = recvmmsg(
            socket_fd,
            messages,
            (unsigned int)batch_size,
            MSG_WAITFORONE,
            NULL);

        if (received < 0) {
            if (errno == EINTR && stop_requested) {
                break;
            }
            if (errno == EINTR) {
                continue;
            }

            perror("recvmmsg");
            break;
        }

        if (call_started_active) {
            state.recvmmsg_calls++;
            state.messages_returned += (uint64_t)received;
            if ((unsigned int)received > state.maximum_batch_returned) {
                state.maximum_batch_returned = (unsigned int)received;
            }
        }

        for (int index = 0; index < received; index++) {
            process_datagram(
                &state,
                buffers + (size_t)index * MAX_DATAGRAM_SIZE,
                messages[index].msg_len,
                &senders[index],
                periodic_reports);
        }
    }

    printf("\nReceiver stopped\n");

    free(state.seen_sequences);
    free(messages);
    free(vectors);
    free(senders);
    free(buffers);
    close(socket_fd);
    return EXIT_SUCCESS;
}
