import socket
import utils
from utils import States

UDP_IP = "127.0.0.1"
UDP_PORT = 5005

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
            resp_header = utils.Header(next_seq_num, ack_number, syn=1, ack=1)

            if utils.DEBUG:
                print("[DEBUG] Received SYN")
                print("[DEBUG] Sending SYNACK")
                print(f"[DEBUG] SEQ: {resp_header.seq_num} | ACK: {resp_header.ack_num}")                    

        case States.SYN_SENT:
            if header.ack == 1:
                # update the state client is now established
                update_server_state()
                continue

        case States.ESTABLISHED:
            if not header.fin:
                # append body to the message
                message += body

                if utils.DEBUG:
                    print("[DEBUG] Server received message:", body)
                
                ack_number = header.seq_num + 1
                resp_header = utils.Header(next_seq_num, ack_number, syn=1, ack=1)

            else:
                ack_number = header.seq_num + 1
                resp_header = utils.Header(next_seq_num, ack_number, syn=0, ack=1)

                # update the state and send message
                update_server_state()
            sock.sendto(resp_header.bits(), addr)
            next_seq_num += 1

        case States.CLOSE_WAIT:
            # TODO: Update seq and ack number to account for data transmission
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

    if resp_header and server_state is not States.ESTABLISHED:
        sock.sendto(resp_header.bits(), addr)
        next_seq_num += 1
