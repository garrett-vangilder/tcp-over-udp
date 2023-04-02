from multiprocessing import Value
import time
from utils import States
import socket
import utils

UDP_IP = "127.0.0.1"
UDP_PORT = 5005
MSS = 12  # maximum segment size

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)  # Internet  # UDP


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
    last_received_ack = -1
    last_received_seq = -1

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

        # several state changes necessary in this process, open a while loop
        while True:
            # initialize the message, in the case of a handshake its just a header
            header = None

            # if we've sent a syn message, we need to wait for a syn_ack message
            if self.client_state == States.SYN_SENT:
                # wait for response from server
                self.receive_ack()

            match self.client_state:
                case States.CLOSED:
                    # Create a random sequence number
                    seq_num = utils.rand_int()

                    # Create a header
                    header = utils.Header(seq_num, 0, syn=1, ack=0)

                    # Initialize last received ack and seq num
                    self.last_received_ack = -1
                    self.last_received_seq = -1

                case States.SYN_SENT:
                    # if we receive a syn message we need to enter ESTABLISHED state
                    if self.last_received_ack == seq_num + 1:
                        # set the ack number to the received seq_num + 1
                        self.last_received_seq += 1

                        header = utils.Header(
                            self.last_received_ack, self.last_received_seq, syn=0, ack=1
                        )

                case _:
                    return

            # send the message
            send_udp(header.bits())

            # update the state
            self.update_state()

    def terminate(self):
        """
        Terminate the connection in the same multi-step process as the handshake via state machine.
        :return: None
        """
        # sequence number should be last received ack
        seq_num = self.last_received_ack + 1
        ack_num = self.last_received_seq

        while True:
            # initialize the message, in the case of a terminate its just a header
            header = None

            # if we've sent a fin message, we need to wait for a fin_ack message
            if self.client_state in {States.FIN_WAIT_1, States.FIN_WAIT_2}:
                # wait for response from server
                self.receive_ack()
         

            match self.client_state:
                case States.ESTABLISHED:
                    # Create a header
                    header = utils.Header(seq_num, ack_num, syn=1, ack=0, fin=1)

                case States.FIN_WAIT_1:
                    # increments the last received ack but do not send a response
                    if self.last_received_ack == seq_num + 1:
                        self.last_received_seq += 1

                case States.FIN_WAIT_2:
                    # send the final ack
                    header = utils.Header(
                        self.last_received_ack, self.last_received_seq, syn=0, ack=1
                    )

                case States.TIME_WAIT:
                    # wait 30 seconds and then close
                    time.sleep(30)

                case _:
                    return

            if header:
                # send the message
                send_udp(header.bits())

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
        if utils.DEBUG:
            print("[DEBUG] Sending message:", message)
        if self.client_state is States.ESTABLISHED:
            # create a new message
            header = utils.Header(
                self.last_received_ack, self.last_received_seq, syn=0, ack=1
            )

            # send the message
            send_udp(header.bits() + message.encode())


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


# necessary for freeze_support
if __name__ == "__main__":
    # we create a client, which establishes a connection
    client = Client()
    # we send a message
    client.send_reliable_message("This message is to be received in pieces")
    # we terminate the connection
    client.terminate()
