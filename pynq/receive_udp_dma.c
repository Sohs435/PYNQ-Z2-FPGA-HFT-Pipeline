struct hft_receiver *hft_receiver_open(
    const char *listen_ip,
    uint16_t listen_port,
    unsigned int batch_size,
    unsigned int timeout_ms,
    int requested_socket_buffer)
{
    if (listen_ip == NULL || listen_port == 0 || batch_size == 0
        || batch_size > MAX_RECEIVE_BATCH || timeout_ms == 0
        || requested_socket_buffer <= 0) {
        errno = EINVAL;
        return NULL;
    }

    struct hft_receiver *receiver = calloc(1, sizeof(*receiver));
    if (receiver == NULL) {
        return NULL;
    }
    receiver->socket_fd = -1;
    receiver->batch_size = batch_size;

    receiver->messages = calloc(batch_size, sizeof(*receiver->messages));
    receiver->vectors = calloc(batch_size, sizeof(*receiver->vectors));
    receiver->senders = calloc(batch_size, sizeof(*receiver->senders));
    receiver->buffers = calloc(batch_size, MAX_DATAGRAM_SIZE);
    if (receiver->messages == NULL || receiver->vectors == NULL
        || receiver->senders == NULL || receiver->buffers == NULL) {
        goto fail;
    }

    for (unsigned int index = 0; index < batch_size; index++) {
        receiver->vectors[index].iov_base =
            receiver->buffers + (size_t)index * MAX_DATAGRAM_SIZE;
        receiver->vectors[index].iov_len = MAX_DATAGRAM_SIZE;
        receiver->messages[index].msg_hdr.msg_name =
            &receiver->senders[index];
        receiver->messages[index].msg_hdr.msg_namelen =
            sizeof(receiver->senders[index]);
        receiver->messages[index].msg_hdr.msg_iov =
            &receiver->vectors[index];
        receiver->messages[index].msg_hdr.msg_iovlen = 1;
    }

    receiver->socket_fd = socket(AF_INET, SOCK_DGRAM, 0);
    if (receiver->socket_fd < 0) {
        goto fail;
    }

    int reuse_address = 1;
    struct timeval timeout = {
        .tv_sec = timeout_ms / 1000U,
        .tv_usec = (timeout_ms % 1000U) * 1000U,
    };
    if (setsockopt(receiver->socket_fd, SOL_SOCKET, SO_REUSEADDR,
                   &reuse_address, sizeof(reuse_address)) < 0
        || setsockopt(receiver->socket_fd, SOL_SOCKET, SO_RCVBUF,
                      &requested_socket_buffer,
                      sizeof(requested_socket_buffer)) < 0
        || setsockopt(receiver->socket_fd, SOL_SOCKET, SO_RCVTIMEO,
                      &timeout, sizeof(timeout)) < 0) {
        goto fail;
    }

    struct sockaddr_in listen_address = {0};
    listen_address.sin_family = AF_INET;
    listen_address.sin_port = htons(listen_port);
    if (inet_pton(AF_INET, listen_ip, &listen_address.sin_addr) != 1) {
        errno = EINVAL;
        goto fail;
    }
    if (bind(receiver->socket_fd, (struct sockaddr *)&listen_address,
             sizeof(listen_address)) < 0) {
        goto fail;
    }

    return receiver;

fail: {
        int saved_errno = errno;
        hft_receiver_close(receiver);
        errno = saved_errno;
        return NULL;
    }
}

/*
 * One blocking recvmmsg call. The first datagram may block until timeout;
 * MSG_WAITFORONE then drains other datagrams already waiting in the socket.
 * Each valid-sized payload is copied into the matching 32-byte result slot.
 * A datagram larger than 2048 bytes is marked MSG_TRUNC and never copied.
 * Returns a count, or -1 with errno set. No DMA operation happens here.
 */
int hft_receiver_receive(
    struct hft_receiver *receiver,
    struct hft_rx_slot *results,
    unsigned int result_capacity)
{
    if (receiver == NULL || results == NULL
        || result_capacity < receiver->batch_size) {
        errno = EINVAL;
        return -1;
    }

    for (unsigned int index = 0; index < receiver->batch_size; index++) {
        receiver->messages[index].msg_len = 0;
        receiver->messages[index].msg_hdr.msg_namelen =
            sizeof(receiver->senders[index]);
        receiver->messages[index].msg_hdr.msg_flags = 0;
    }

    int received = recvmmsg(receiver->socket_fd, receiver->messages,
                            receiver->batch_size, MSG_WAITFORONE, NULL);
    if (received < 0) {
        return -1;
    }

    for (int index = 0; index < received; index++) {
        struct hft_rx_slot *slot = &results[index];
        const struct mmsghdr *message = &receiver->messages[index];
        slot->length = message->msg_len;
        slot->flags = message->msg_hdr.msg_flags;
        memcpy(slot->sender_ip,
               &receiver->senders[index].sin_addr.s_addr,
               sizeof(slot->sender_ip));
        slot->sender_port = ntohs(receiver->senders[index].sin_port);
        slot->reserved = 0;

        if (slot->length == HFT_PACKET_SIZE && !(slot->flags & MSG_TRUNC)) {
