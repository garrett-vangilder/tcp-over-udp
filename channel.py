from multiprocessing import Value
from threading import Timer
import threading
from utils import States
import multiprocessing
import random
import socket
import time
import utils

UDP_IP = "127.0.0.1"
UDP_PORT_CHANNEL = 5007
UDP_PORT_SERVER = 5008

# order of execution starting scripts: (1) channel, (2) server, then (3) client
# so in 3 terminals, do the following in order:
# terminal 1: python channel.py
# terminal 2: python server.py
# terminal 3: python client.py

# this is a bidirectional channel sitting between client and server
# client talks to channel, then channel to server
# phrased another way, the channel is the "server" for the client
# server talks to channel, then channel to client
# phrased another way, the server is the "server" for the channel

# channel binds to UDP_PORT_CHANNEL to listen to client
# server binds to UDP_PORT_SERVER to listen to channel
# responses go back to auto-generated ports at client and channel

# in your client, you need to use UDP_PORT_CHANNEL
# e.g., set UDP_PORT = 5007

# in your server, you need to use UDP_PORT_SERVER
# e.g., set UDP_PORT = 5008

# assumptions / guarantees:
# the implementation is not fully concurrency safe and depends upon 
# eventual resends, otherwise it may fail or hang

# the channel should not drop the initial 3-way handshake or 4-way teardown messages
# the channel assumes the header has a fin field with the fin bit, checking naming in utils.py
# the channel may delay and drop any other messages (client->server msgs and server->client acks)

# the channel does NOT buffer messages in the current form, so it 
# likely will only work with stop-and-wait for client/server
# because it does not buffer messages, this also means the channel will NOT
# reorder messages

# however, because a dropped ack can result in the client resending a message, 
# it can result in duplicated messages at the server due to these resends (so 
# same payload can be received by server twice), so the 
# server should handle duplications, which can be done based on 
# the sequence numbers and keeping track at the server what data 
# has been received so far

# TODO: buffering could be added, probably using queue.LifoQueue for no reordering,
# and maybe queue.PriorityQueue with reordering, where the priority of incoming 
# messages is used to represent any (say random) reordering

# socket for client <-> channel communication
sock_client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM) # UDP
sock_client.bind((UDP_IP, UDP_PORT_CHANNEL))

# socket for channel <-> server communication
sock_server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM) # UDP

# timeouts to prevent socket recvs from potentially hanging
sock_client.settimeout(6.0)
sock_server.settimeout(6.0)

# small sleep: to reduce latency (can speed testing), set as small as possible (~0.05)
# to test higher latency channels, try ~0.25
sleep_v = 0.05

# max delay as multiple of sleep_v; do not set too high, otherwise can cause timeouts
# if you see client/server timeouts, may need to adjust timeouts in your client/server
# recommended client timeout: ~3s with these default parameters
# the total max channel delay is set as the product sleep_v * sleep_factor
# with sleep_v = 0.05, factor can be up to ~20
# with sleep_v = 0.25, factor can be up to ~4
sleep_factor = 4

# used to terminate threads if needed (on ctrl+c, etc.)
event_terminate = threading.Event()

# messages can be dropped from client to server AND from server to client
# probability is uniformly distributed in range 0.0 to 1.0
# for initial testing, suggest using a small value (0.01, so ~1% messages dropped)
# for final testing, suggest using a large value (0.5, so ~50% messages dropped)
# untested, but 0.0 should be an ideal channel (no drops) but with delays
p_drop_server = 0.0 # (roughly) probability to drop an ack from server
p_drop_client = 0.0 # (roughly) probability to drop a message from client

round = 0 # used for some startup synchronization
event_wait_send = threading.Event() # used for some recurring synchronization ordering sends/recvs
teardown_started = False # flag used to not drop messages once teardown has started
round_startup = 2 # number of rounds of communication to wait before dropping messages (so connection is established)
addr_client = [] # client address information, used so channel can send back to client

# client listener/sender, forwards client messages to server
def chan_client():
	global sock_client, sock_server, event_wait_send, addr_client, teardown_started, round
	while True:
		if event_terminate.is_set():
			break
	
		print('waiting on client')
		
		try:
			data_client, addr_client = sock_client.recvfrom(1024)
		except socket.timeout:
			# this was not needed on python 3.8+
			# on python 3.7.x, this exception is needed to prevent hangs
			# probably a concurrency bug or relationship of timeout values
			# in client/server implementations
			# for this case, the message truly is lost, but 
			# if client/server implement reliable transfer 
			# (e.g., stop and wait), should be okay (was in our solution
			# at least tested with 50% message/ack loss probability 
			# with success)
			# the same exception has been added on the server channel for the 
			# same reasoning
			#
			# note: these timeouts can occur if enough msgs/acks are dropped in a row
			# but if client/server resend is working properly, should not matter
			print('EXCEPTION: client channel timeout, message lost')
			continue
		
		header = utils.bits_to_header(data_client)
		
		channel_wait = random.uniform(sleep_v,sleep_factor * sleep_v)
		time.sleep(channel_wait)
		print("channel delaying client->server for ", channel_wait, "s")

		if header.fin == 1:
			teardown_started = True

		# drop messages randomly, after connection established
		# avoid dropping connection establishment and teardown messages
		if round >= round_startup and \
		  (header.ack == 0 and header.syn == 0 and header.fin == 0) and \
		  random.uniform(0.0,1.0) <= p_drop_client and \
		  not teardown_started:
			
			print("DROPPING MESSAGE FROM CLIENT")
			continue

		print('channel forwarding to server')
		sock_server.sendto(data_client, (UDP_IP, UDP_PORT_SERVER))
		time.sleep(sleep_v)
		
		# notify that server has sent without dropping, needed for ordering sends/receives, otherwise can hang
		event_wait_send.set()

# server listener/sender, forwards server messages to client
def chan_server():
	global sock_client, sock_server, event_wait_send, addr_client, round, teardown_started
	while True:
		if event_terminate.is_set():
			break

		print('waiting on server response (can hang if server does not resend)')
		
		# primitive synchronization
		# need to wait until initial client message sent
		# to server, otherwise socket from server 
		# is not valid (so sock_server.recvfrom will error)
		event_wait_send.wait()
		
		event_wait_send.clear()

		try:
			data_server, addr_server = sock_server.recvfrom(1024)
		except socket.timeout:
			print('EXCEPTION: server channel timeout, message lost')
			continue
		
		header = utils.bits_to_header(data_server)

		# drop messages randomly
		# avoids dropping connection establishment and teardown messages
		if round >= round_startup and \
		  (header.ack == 1 and header.syn == 0 and header.fin == 0) and \
		  random.uniform(0.0,1.0) <= p_drop_server and \
		  not teardown_started:
			print("DROPPING ACK FROM SERVER")
			continue
		
		print('channel forwarding to client')

		channel_wait = random.uniform(sleep_v, sleep_factor * sleep_v)
		time.sleep(channel_wait)
		print("channel delaying server->client for ", channel_wait, "s")

		sock_client.sendto(data_server, (UDP_IP, addr_client[1]))
		time.sleep(sleep_v)
		round = round + 1

t_client = threading.Thread(target=chan_client)
t_server = threading.Thread(target=chan_server)

t_client.start()
time.sleep(2)
t_server.start()

# main loop for keeping client/server threads running and termination handling
while True:
	try:
		time.sleep(5)
		print("round: ", round, "ongoing, waiting 5s (threads sampled faster)")
		print() # newline

		if not t_client.is_alive() or not t_server.is_alive():
			print("shutting down channel, client/server threads not running")
			event_terminate.set()
			break
	except:
		event_terminate.set()
		break
