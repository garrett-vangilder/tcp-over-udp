import socket
import utils
from utils import States

UDP_IP = "127.0.0.1"
# UDP_PORT = 5005

# reference to our channel
UDP_PORT = 5008

# initial server_state
server_state = States.CLOSED

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)  # Internet  # UDP

sock.bind((UDP_IP, UDP_PORT))  # wait for connection

# initialize the message
message = ""

# initialize the received header, body and addr
header = None
body = None
addr = (
    None,
    None,
)

# this is used to keep track of the last received sequence number to prevent the server
# from incrementing the sequence number when it receives a duplicate message
# or a message is dropped/out of order
last_received_seq_num = 0


# Some helper functions to keep the code clean and tidy
def _update_server_state(new_state):
    """
    Update the server state and print the transition if in debug mode.
    :param new_state: the new state
    :return: None
    """
    global server_state

    # print the transition if in debug mode
    if utils.DEBUG:
        # print the transition
        print("[STATE CHANGE]", server_state, "->", new_state)

    # update the state
    server_state = new_state


def update_server_state():
    """
    Update the server state based on the current state.
    :return: None
    """
    ORG_STATE_TO_NEW_STATE = {
        States.CLOSED: States.LISTEN,
        States.LISTEN: States.SYN_RECEIVED,
        States.SYN_RECEIVED: States.SYN_SENT,
        States.SYN_SENT: States.ESTABLISHED,
        States.ESTABLISHED: States.CLOSE_WAIT,
        States.CLOSE_WAIT: States.LAST_ACK,
        States.LAST_ACK: States.CLOSED,
    }

    _update_server_state(ORG_STATE_TO_NEW_STATE[server_state])


def recv_msg():
    """
    Receive a message and return header, body and addr
    addr is used to reply to the client
    this call is blocking
    :return: header, body, addr
    """
    data, addr = sock.recvfrom(1024)
    header = utils.bits_to_header(data)
    body = utils.get_body_from_data(data)
    return (header, body, addr)


next_seq_num = 0
# The server is always listening for messages
while True:
    # we need to wait for a client message in these states
    if server_state in {
        States.LISTEN,
        States.SYN_SENT,
        States.ESTABLISHED,
        States.LAST_ACK,
    }:
        if utils.DEBUG:
            print("[DEBUG] Server waiting for message")
        header, body, addr = recv_msg()

    # initialize the response header
    resp_header = None

    match server_state:
        case States.CLOSED:
            pass
        case States.LISTEN:
            # if we receive a syn message we need to enter SYN_RECEIVED state
            if header.syn == 1:
                # create a random sequence number
                seq_number = utils.rand_int()

                # will increment when header is sent
                next_seq_num = seq_number

                # increment the ack number
                ack_number = header.seq_num + 1

        case States.SYN_RECEIVED:
            # Create a header, seq number is defined above
            if header.syn == 1:
                resp_header = utils.Header(next_seq_num, ack_number, syn=1, ack=1)

            if utils.DEBUG:
                print("[DEBUG] Received SYN")
                print("[DEBUG] Sending SYNACK")
                print(
                    f"[DEBUG] SEQ: {resp_header.seq_num} | ACK: {resp_header.ack_num}"
                )

        case States.SYN_SENT:
            if header.ack == 1:
                # update the state client is now established
                update_server_state()

                last_received_seq_num = header.seq_num
                continue

        case States.ESTABLISHED:
            if not header.fin:
                if utils.DEBUG:
                    print("[DEBUG] Server received message:", body)

                ack_number = header.seq_num + 1
                resp_header = utils.Header(next_seq_num, ack_number, syn=1, ack=1)

                if utils.DEBUG:
                    print(
                        "[DEBUG] Previously received sequence number:",
                        last_received_seq_num,
                    )
                    print(
                        "[DEBUG]     Current message sequence number:", header.seq_num
                    )

                # if the seq num is greater than the last received seq num
                # then we can add the body to the message
                # and update the last received seq num
                # otherwise our message was not received
                if header.seq_num > last_received_seq_num:
                    next_seq_num += 1
                    message += body
                    last_received_seq_num = header.seq_num

            else:
                ack_number = header.seq_num + 1
                resp_header = utils.Header(next_seq_num, ack_number, syn=0, ack=1)
                next_seq_num += 1

                # update the state and send message from ESTABLISHED to CLOSE_WAIT
                update_server_state()
            if resp_header:
                sock.sendto(resp_header.bits(), addr)

        case States.CLOSE_WAIT:
            ack_number = header.seq_num + 1
            resp_header = utils.Header(next_seq_num, ack_number, syn=0, ack=0, fin=1)

        case States.LAST_ACK:
            # Check if the client replied with an ack
            if header.ack == 1:
                # update the state
                update_server_state()

                # reset message state
                message = ""

                # reset header, body and addr
                header = None
                body = None
                addr = (None, None)

        case _:
            print("Invalid state")
            exit(1)

    if server_state in {
        States.CLOSED,
        States.LISTEN,
        States.SYN_RECEIVED,
        States.CLOSE_WAIT,
    }:
        update_server_state()

    # send the response header if it exists and the server is not established
    # established state is handled above and is unique enough to break our pattern
    # so we handle it separately. Additionally we must increment the next_seq_num, ESTABLISHED
    # also increments the next_seq_num
    if resp_header and server_state is not States.ESTABLISHED:
        sock.sendto(resp_header.bits(), addr)
        next_seq_num += 1
