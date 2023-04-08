# TCP over UDP


Note: This code only requires python 3.10+

## How to

```bash
# To run the server
python server.py

# To run the client
python client.py
```
## Artifacts

Examples of the service can be found in the `artifacts` directory at the root of the project. 

For the final programming assignment, I have included additional logs from the channel, server, and client. This shows the sequence number, acknowledgment number, and the message bits
for each request. In the case that a body is included, that is also shown. Additionally there are state transfer messages in each log. I have also included a screenshot
of the project running locally.