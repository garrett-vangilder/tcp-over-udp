from multiprocessing import Value
import time
from utils import States
import socket
import utils

UDP_IP = "127.0.0.1"
# UDP_PORT = 5005

# reference to our channel
UDP_PORT = 5007

MSS = 12  # maximum segment size

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)  # Internet  # UDP

# set a timeout for our socket, this is necessary so that we can catch packets that are dropped
sock.settimeout(0.5)


def send_udp(message):
    """
    Send a message to the server.
    :param message: the message to be sent
    :return: None
    """
    sock.sendto(message, (UDP_IP, UDP_PORT))


class Client:
    """
    The client class is responsible for establishing a connection
    with the server and sending a message.
    """

    # Note: These values are set to -1 to indicate that they have not been set
    # and there has not been a message sent/received yet.
    last_received_ack = -1
    last_received_seq = -1

    next_seq_num = 0

    def __init__(self):
        """
        Initialize the client state and start the handshake process.
        """
        self.client_state = States.CLOSED
        self.handshake()

    def handshake(self):
        """
        Perform the handshake process.
        :return: None
        """
        recv_header = None
        syn_header = None
        synack_header = None
        # several state changes necessary in this process, open a while loop
        while True:
            # if we've sent a syn message, we need to wait for a syn_ack message
            if self.client_state == States.SYN_SENT:
                # wait for response from server, set an infinite loop until we get a response
                # if timeout occurs, we will continue to wait, this is where the stop and wait occurs
                while True:
                    try:
                        recv_header = self.receive_ack()
                    except socket.timeout:
                        continue
                    break

            match self.client_state:
                case States.CLOSED:
                    # Create a random sequence number
                    seq_num = utils.rand_int()

                    # will increment when message is sent
                    self.next_seq_num = seq_num

                    # Create a header
                    syn_header = utils.Header(seq_num, 0, syn=1, ack=0)

                    if utils.DEBUG:
                        print("[DEBUG] Sending SYN")
                        print(
                            f"[DEBUG] SEQ: {syn_header.seq_num} | ACK: {syn_header.ack_num}"
                        )

                    # send the message
                    send_udp(syn_header.bits())

                    # increment sequence number
                    self.next_seq_num += 1

                case States.SYN_SENT:
                    # validate incoming message is correct
                    if recv_header.syn == 1 and recv_header.ack == 1:
                        ack_number = self.last_received_seq + 1
                        synack_header = utils.Header(
                            self.next_seq_num, ack_number, syn=0, ack=1
                        )

                        if utils.DEBUG:
                            print("[DEBUG] Sending ACK")
                            print(
                                f"[DEBUG] SEQ: {synack_header.seq_num} | ACK: {synack_header.ack_num}"
                            )

                        # send the message
                        send_udp(synack_header.bits())

                        # increment sequence number
                        self.next_seq_num += 1

                case _:
                    return

            # update the state
            self.update_state()

    def terminate(self):
        """
        Terminate the connection in the same multi-step process as the handshake via state machine.
        :return: None
        """
        # sequence number should be last received ack
        seq_num = self.next_seq_num
        ack_num = self.last_received_seq

        while True:
            # initialize the message, in the case of a terminate its just a header
            header = None

            # if we've sent a fin message, we need to wait for a fin_ack message
            if self.client_state in {States.FIN_WAIT_1, States.FIN_WAIT_2}:
                
                # wait for response from server, set an infinite loop until we get a response
                # if timeout occurs, we will continue to wait until the message is received
                while True:
                    try:
                        self.receive_ack()
                    except socket.timeout:
                        continue
                    break

            match self.client_state:
                case States.ESTABLISHED:
                    # Create a header
                    header = utils.Header(
                        self.next_seq_num, ack_num, syn=1, ack=0, fin=1
                    )

                    if utils.DEBUG:
                        print("[DEBUG] Sending FIN")
                        print(f"[DEBUG] SEQ: {header.seq_num} | ACK: {header.ack_num}")

                case States.FIN_WAIT_1:
                    # increments the last received ack but do not send a response
                    if self.last_received_ack == seq_num + 1:
                        self.last_received_seq += 1

                case States.FIN_WAIT_2:
                    # send the final ack
                    header = utils.Header(
                        self.next_seq_num, self.last_received_seq, syn=0, ack=1
                    )

                    if utils.DEBUG:
                        print("[DEBUG] Sending FINACK")
                        print(f"[DEBUG] SEQ: {header.seq_num} | ACK: {header.ack_num}")

                case States.TIME_WAIT:
                    # wait 30 seconds and then close
                    time.sleep(30)

                case _:
                    return

            if header:
                # send the message
                send_udp(header.bits())
                self.next_seq_num += 1

            self.update_state()

    def update_state(self):
        """
        Update the state of the client.
        :return: None
        """
        ORG_STATE_TO_NEW_STATE = {
            States.CLOSED: States.SYN_SENT,
            States.SYN_SENT: States.ESTABLISHED,
            States.ESTABLISHED: States.FIN_WAIT_1,
            States.FIN_WAIT_1: States.FIN_WAIT_2,
            States.FIN_WAIT_2: States.TIME_WAIT,
            States.TIME_WAIT: States.CLOSED,
        }

        self._update_state(ORG_STATE_TO_NEW_STATE[self.client_state])

    def _update_state(self, new_state):
        """
        Update the state of the client.
        :param new_state: The new state of the client.
        :return: None
        """
        if utils.DEBUG:
            print(self.client_state, "->", new_state)
        self.client_state = new_state

    def send_reliable_message(self, message):
        """
        Send a reliable message to the server. Via stop-and-wait
        :param message: The message to send.
        :return: None
        """
        if self.client_state is States.ESTABLISHED:
            # chunk message into MSS sized chunks
            chunks = [message[i : i + MSS] for i in range(0, len(message), MSS)]
            # create a new message for each chunk
            for chunk in chunks:
                while True:
                    # get size of chunk in bytes
                    chunk_size = len(chunk.encode())

                    # next_seq_num is the sequence number of the next message
                    # needs to account for chunk size
                    seq_num = self.next_seq_num + chunk_size

                    if utils.DEBUG:
                        print(f"[DEBUG] Chunk size: {chunk_size}")
                        print(f"[DEBUG] Next SEQ: {self.next_seq_num}")
                        print(f"[DEBUG] SEQ: {seq_num}")

                    header = utils.Header(
                        seq_num, self.last_received_seq + 1, syn=0, ack=0
                    )

                    if utils.DEBUG:
                        print("[DEBUG] Sending message:", chunk)
                        print(f"[DEBUG] SEQ: {header.seq_num} | ACK: {header.ack_num}")

                    # send the message
                    send_udp(header.bits() + chunk.encode())

                    try:
                        # wait for ack
                        header = self.receive_ack()
                    except socket.timeout:
                        # we should retry sending the message
                        continue

                    # is the ack valid?
                    if header.ack_num > self.next_seq_num:
                        # update the next sequence number and break from the loop
                        self.next_seq_num += chunk_size
                        break

    def receive_ack(self):
        """
        Receive acks from the server, update the last_received_ack
        :return: None
        """
        # initialize the last received ack
        last_received_ack = self.last_received_ack
        last_received_seq = self.last_received_seq

        # receive data from the server
        recv_data, _ = sock.recvfrom(1024)

        # convert the received data to a header
        header = utils.bits_to_header(recv_data)

        if header.ack_num > last_received_ack:
            last_received_ack = header.ack_num

        if header.seq_num > last_received_seq:
            last_received_seq = header.seq_num

        # update the last received ack
        self.last_received_ack = last_received_ack
        self.last_received_seq = last_received_seq

        return header


# necessary for freeze_support
if __name__ == "__main__":
    # we create a client, which establishes a connection
    client = Client()
    # we send a message
    client.send_reliable_message("This message is to be received in pieces")
    # we terminate the connection
    client.terminate()
