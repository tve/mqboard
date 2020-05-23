# MicroPython Asynchronous MQTT

The `mqtt_async` library implements a MQTT 3.1.1 client with support for
QoS 0 and QoS 1 messages. It uses Micropython's new (in 2020) built-in asyncio / uasyncio
and supports streaming QoS 1 messages by overlapping processing with ACKs.
The implementation is a rewrite inspired by and largely API compatible with
[Peter Hinch's version](https://github.com/peterhinch/micropython-mqtt).

Some of the special features of this library:
- Fully integrated with the new MicroPython built-in uasyncio.
- Supports QoS 0 and QoS 1 with automatic retries when sending QoS 1 messages.
- Automatic keep-alive messages and disconnect/reconnect when the connection to the broker ceases to
  function.
- Supports TLS.
- Disconnect/reconnect first acts at the TCP connection level and only when unsuccessful moves
  to reconnect Wifi.
- Publishing messages at QoS 1 can be asynchronous such that the application can proceed before an
  ACK is received from the broker.
- Support starting with a clean session or resuming from a previous session.

`mqtt_async` is published under an MIT license.

## Getting Started

This library **requires** the use of the new `uasyncio` module built-into MicroPython as of the
merge of [PR 5796](https://github.com/micropython/micropython/pull/5796) on March 25th 2020. In
terms of MP releases this will mean V1.13 or greater. I highly recommend building MP from source
yourself, but there is a download available, see below.

Using TLS **requires** a number of PRs that are in the pipeline. Your best bet at this point
is to use the author's MP firmware at https://github.com/tve/micropython (in the default `tve`
branch). (The PRs no longer merge cleanly due to the ever-evolving MP master HEAD...)

### Installation

You can:
- copy the `mqtt_async.py` file to your board, e.g., `pyboard.py -f cp mqtt_async.py :`
- cross-compile the library to an mpy file and upload that
- skip `micropython-logging` as there is a fall-back

An old version is available via upip, it's useless right now:

```
import upip
upip.install('micropython-mqtt-async')
upip.install('micropython-logging')
```

### Hello World

The following code is also available as `hello_world.py` in this repo.

```
from mqtt_async import MQTTClient, config
import uasyncio as asyncio

# Change the following configs to suit your environment
TOPIC           = 'test/mqtt_async'
config.server   = '192.168.0.14' # can also be a hostname
config.ssid     = 'wifi-ssid'
config.wifi_pw  = 'wifi-password'

def callback(topic, msg, retained, qos): print(topic, msg, retained, qos)

async def conn_callback(client): await client.subscribe(TOPIC, 1)

async def main(client):
    await client.connect()
    n = 0
    while True:
        print('publish', n)
        await client.publish(TOPIC, 'Hello World #{}!'.format(n), qos=1)
        await asyncio.sleep(5)
        n += 1

config.subs_cb = callback
config.connect_coro = conn_callback

client = MQTTClient(config)
loop = asyncio.get_event_loop()
loop.run_until_complete(main(client))
```

Sample run:
```
> ./pyboard.py --device /dev/ttyUSB0 hello-world.py
INFO:mqtt_async:Connecting to ('192.168.0.14', 1883) id=b'246f282eb7c0' clean=0
publish 0
b'test/mqtt_async' b'Hello World #0!' False 1
publish 1
b'test/mqtt_async' b'Hello World #1!' False 1
publish 2
```

Next, check out the API docs further down...

## Open issues and planned changes

- The Wifi management will be split out from this library. This will simplify the config, will
  make it more obvious to use the library without it messing with Wifi, and to load a different
  wifi manager for each platform. At the end of the day the only interaction between MQTT and
  wifi is (a) a notification "hey wifi, are you sure you're still connected? Maybe you should
  bounce the network!" and (b) a notification "hey MQTT, try to connect again!".
- The callbacks have poor names and should be lists, the plan is to merge `../mqboard/mqtt.py`
  into `mqtt_async.py`. Except that things will change further by splitting Wifi management off.
- The error handling needs tuning. Overall the principle is to let exceptions propagate up to 
  the caller. In some cases they're caught in order to print troubleshooting info and re-raised.
  In particular, when out-of-memory hits there may be smart things that could be done, for example,
  dropping incoming messages, although if they use QoS=1 they will come again...

## Implementation Specifics

### Hardware platforms.

This library has been tested with Micropython compiled with ESP-IDFv4 on an esp32, this is the
recommended configuration.
Using ESP-IDFv3 has not been tested.

The source code contains code to handle the esp8266 but it has not been tested and has been
commented out.  The library has to be frozen into the firmware in order to be usable and even
then it's questionable whether the esp8266 has enough memory to do anything useful.
The author does not expect to test with the esp8266 but will accept PRs that don't significantly
increase code size for other platforms.

### Compatibility with the original mqtt_as

The API of MQTTClient in `mqtt_async` is similar to the original `mqtt_as`:
- `subscribe()` is the same
- `publish()` has an optional `sync` parameter
- the `subs_cb` callback has 5 parameters, adding `qos` and `dup` parameters.
- the config dict has been changed significantly, see its description
- a number of auxiliary methods have been dropped, they could be re-added

The implementation, however, has been rewritten resulting in the following semantic changes:

1. Support sending streams of MQTT messages at QoS=1 without blocking for an ACK after each message.
   This allows streaming of data using relatively small messages at high data rates.
1. Almost full test coverage via automated tests. The lower-level protocol class is tested on a
   Micropython board against a real broker to ensure protocol correctness and that failures are
   reported appropriately.
   The higher-level client class is tested on linux using a simulated protocol class to test
   failures and retransmissions.
1. The implementation is completely reorganized to facilitate automated testing and to accurately
   handle retransmissions across connection reconnects which enables the implementation of the
   streaming.
   Specifically, the implementation is split such that a lower-level class (`MQTTProto`) implements
   the protocol on a single socket and a higher-level class (`MQTTClient`) implements the
   reconnection and retransmission logic.
1. Messages that normally fit into a TCP packet get sent as a single packet on the wire to reduce
   overall overhead thereby improving performance.
1. Retransmission of messages on an existing TCP connection is eliminated because it is
   pointless given that TCP implements a reliable stream (it is impossible for an application to
   receive data that was sent on a connection after previous data got "lost" or "corrupted").
   Instead, if no ACK is received, the retransmission uses a fresh connection from the get-go.
1. Accurately retransmit packets on a fresh connection using the original PID (packet ID) to
   avoid unnecessary duplicate packets.
1. When reconnecting, first do so at the TCP level without tearing Wifi down to minimize the
   disruption, only disconnect/reconnect Wifi if the TCP reconnect doesn't work.
1. Eliminate `clean_init` config param and only use clean config param, see below.
1. Structure imports and work-arounds such that `mqtt_async` can be used in CPython and tests can
   use `pytest`.
1. Use the standard logging facility instead of ad-hoc debug messages.

### Streaming data using small messages

In general MQTT supports sending a long stream of data by breaking it up into small messages that
are all sent to the same topic using QoS=1. The protocol guarantees in-order delivery of those
messages such that the receiver can easily process them and only needs to check for duplicates, this
is codified in [section 4.6 of the MQTT 3.1.1 spec](http://docs.oasis-open.org/mqtt/mqtt/v3.1.1/os/mqtt-v3.1.1-os.html#_Toc398718105).

When sending messages using `publish()` the default (`sync=True`) is to send the message and
then block to wait for an MQTT-level ACK.
This wait impacts the rate at which a stream of small messages can be transmitted.
`mqtt_async` adds a `sync` parameter to `publish()` which, if set to `False`, omits
the wait allowing the wait for the ACK to be overlapped with producing the next message.

In order to send N messages reliably in-order an application can send the first N-1 messages
using `qos=1` and `sync=False` and then send the last message using `qos=1` and`sync=True`.
Once the last publish completes the broker has received all messages in order.
(Note that the in-order guarantee only applies if the N messages are sent to one and the same
topic!)

From a throughput point of view on an esp32 sending messages with a payload of 2800 bytes appears
close to optimal.
This size fits into two TCP segments (unless the topic is very long or the packets go through a
network link with unusually low MSS) and can generally be pushed into the network stack without
blocking.
Use 1400 bytes to make messages fit into one TCP segment and to consume less memory.

### How to use the clean session flag

In MQTT the broker stores some data for each client, specifically the list of subscriptions and any
pending or unacked messages. This storage allows clients to disconnect and reconnect without loosing
messages. The `clean` flag allows a client to signal to the broker to drop any stored data and start
afresh. This is useful when the application changes and needs a different set of subscriptions or
when a client starts and does not want a deluge of possibly old messages to be delivered.

Unfortunately the semantics of the MQTT `clean` session flag are a little more complicated than
it may seem at first sight.
The `mqtt_async` library implements the following two use-cases:
1. Clients that want a clean slate as they connect, i.e. no old subscriptions and no queued
   messages, should set `config.clean = True`. Under the hood the `MQTTClient` will connect with
   `clean=True`, then disconnect and reconnect with `clean=False`. All subsequent automatic
   reconnections will use `clean=False`.
2. Clients that want to not miss any messages while they we reset or updated should set
   `clean=False`. Under the hood the `MQTTClient` will use that setting for all its connections.

It does not seem to make sense for `MQTTClient` to set `clean=True` for any of its automatic
reconnections. Any use-case that might suggest that is probably a poor match for `mqtt_async` and
could use a much simpler library.

Note that all the above discussion about saved state is linked to the client ID (set in
`config.client_id`). An application can also get a slean slate by switching to a different
client id.

As note to the curious, the connect-disconnect-reconnect to implement the "clean slate" semantics
is necessary because of the following statement from the spec:

> If CleanSession is set to 1, the Client and Server MUST discard any previous Session and start
> a new one. This Session lasts as long as the Network Connection. State data associated with
> this Session MUST NOT be reused in any subsequent Session [MQTT-3.1.2-6].

The last sentence means that state is dropped not just at the start but also at the end of that
session, which would mean that if a network hiccup caused a disconnect-reconnect in `MQTTClient`
state would be lost.

### Testing strategy

The `mqtt_async` library uses a multi-level strategy for testing. Some tests are manual, some are
automated and run on linux, some run on an esp32, some run against a simulated broker and some run
against a real broker. Life is sometimes complicated...

`test_client.py` contains high-level tests for the `MQTTClient` class. If run using `pytest
test_client.py` these tests use a simulated broker (note that the `pytest-timeout` and
`pytest-asyncio` plugins are required). These tests check basic functioning, then check failure
handling (retransmission if qos>0), and finally check async publishing. The async publishing tests
can also be run against a real broker, for this purpose fix-up the broker details at the start of
the file, set `FAKE=False` near the end of the file, and run `pytest -k async_pub test_client.py`.

`test_proto.py` contains lower-level tests for the `MQTTProto` class to ensure that it handles
socket operations correctly and formats and parses MQTT messages properly. To run these tests against
a real broker fix-up the broker info at the start of the file and run `pytest test_proto.py`. These
tests can also be run on a Micropython board to ensure that the idiosyncracies of the socket
interface there are handled correctly. For this purpose start by manually connecting your board to
Wifi, then run something like `pyboard -f cp mqtt_async.py :` followed by
`pyboard test_proto.py`.

With the broker info fixed-up in `test_proto.py` it is also possible to run
`pytest --cov=mqtt_async --cov-report=html` to run all tests and produce a code coverage report in
`./htmlcov`. As of this writing the coverage is in the high eighties percent.

`test-bench.py` is a benchamrk to test the performance of streaming publishing vs. non-streaming.

`test-tcp.py` is a low-level test that can be run manually on a board to test the behavior of the
socket library and networking stack. It requires simulating failures manually for example using
iptables on the broker end to block the flow of packets. The results then require manual
interpretation, but the end goal is to ensure that the behavior of socket operations under failure
is understood. Comments at the start of the file capture some of the observations made on the esp32.

`test-clean.py` is also a manual test that was used to ascertain the behavior of the clean flag when
creating a session. It is not useful as a unit test and kept for posteriority...


## MQTTClient class

#### `__init__(config)` (constructor)

The constructor initializes an `MQTTClient` instance with the provided configuration.
The configuration is a dict for which default values are provided by `mqtt_async.config`
(which is merged into `config` in `__init__` unlike the way it works in `mqtt_as`).

The following `config` elements must be set:
- `server`: MQTT broker hostname or IP address, no default.
- `subs_cb`: `def` function that is run when a message arrives on a topic, default: None.

The following `config` elements are optional but recommended:
- `ssid`: WiFi SSID to connect or reconnect Wifi in case of failure, default: None.
- `wifi_pw`: WiFi password, default: None.

Optional `config` elements:
- `ssl_params`: enable TLS with the provided parameters, like `ussl.wrap_socket`, example:
  `{ "server_hostname": "core.voneicken.com" }`, default: None (disables TLS/SSL).
- `connect_coro`: `async def` function that is run when the first MQTT connection is established, it
  should subscribe to the desired topics, default: None.
- `wifi_coro`: `async def` function that is run with a `status` parameter when an MQTT connection
  starts (`status=True`) or ends (`status=False`), default: None.
- `port`: MQTT broker port, default: 0 which means 8883 if TLS is used, else 1883.
- `client_id`: MQTT client id, default: `machine.unique_id()` in hex.
- `user`: MQTT credentials (if required).
- `password` MQTT password for `user`.
- `clean`: start a clean MQTT session, see above for a discussion, default: True.
- `response_time`: Time in seconds given to the broker to respond before a connection is restarted,
  applies to sub-suback, pub-puback, and ping-pingresp intervals. Default: 10.
- `keepalive`: Time in seconds before broker regards client as having died and sends a last-will
  message. Not relevant if no `will` is set.
- `will`: `MQTTMessage` instance with last-will message, can be set using
  `mqtt_async.set-last-will(topic, message, retain, qos)`, default: None.
- `interface`: should be `network.WLAN(network.STA_IF)` or `WLAN(network.AP_IF)`, default: `STA_IF`.

#### `connect()` (async)

Connects to the specified broker. The application should call
`connect` once on startup. If this fails (due to WiFi or the broker being
unavailable) an `OSError` will be raised and no further action will be taken.
If it succeeds, a background task is started that automatically reconnects if
there is a failure.

#### `start()`

Starts the background task that keeps the connection alive,
which in turn will call `connect()` to get things going.
`start()` is intended to be used instead of `connect()` when there is nothing to do on error.

#### `disconnect()` (async)

Sends a disconnect message to the broker and closes the connection. Sending the disconnect message
suppresses the last-will message in the broker.

It is not possible to reconnect an `MQTTClient` after calling disconnect: create a fresh instance
instead.

#### `publish(topic, msg, retain=False, qos=0, sync=True)` (async)

Publishes the messages with the provided parameters. Topic and msg may be `bytes` or `str`.

If connectivity is not OK `publish` will block until a connection is established.

For QoS 0, `publish` sends the message and returns immediately.

For QoS 1 and `sync==True`, `publish` sends the message then waits for an ACK.

For QoS 1 and `sync==False`, `publish` sends the message then waits for any _previously_
outstanding ACK.

If the connection gets dropped at any point in time `publish` automatically retransmits any unACKed
message.

#### `subscribe(topic, qos=0)` (async)

Subscribes to a topic and awaits an ACK from the broker.
The `qos` parameter specifies at which QoS level the messages will be transmitted by the broker.

It raises an OSError if the subscription fails or the QoS value is not accepted.

Subscriptions should generally be made in the `connect_coro` specified in the config.

If connectivity is not OK `subscribe` will block until a connection is established.

When messages arrive on subscriptions the `subs_cb` is called with the topic, message, retain flag,
QoS level and dup flag as parameters.
The `subs_cb` should be a plain function and reading on the MQTT connection is blocked
until it returns, which it should do promptly. For
incoming QoS=1 messages an acknowledgment is sent to the broker once `subs_cb` returns.

#### `disconnect()` (async)

### Logging

`mqtt_async` uses the standard logging facility through `getLogger("mqtt_async")`.
By default this seems to print INFO messages and higher.
If the `logging` module is not available some simple fall-back functions are used.

A simple way to tune the logging from your application is:

```
import logging
logging.basicConfig(level=logging.DEBUG)
```
Use the `WARNING` level to suppress more messages.

### Timeouts

The `MQTTClient` functions do not use timeouts, that is, if the broker does not respond (possibly
due to there being no connectivity) calls may block forever. Use `asyncio.wait_for()` to introduce
timeouts if desired.

### Not supported

The following methods from `mqtt_as` are not supported:
- `isconnected():` returns `True` if connectivity is OK otherwise it returns `False` and
  schedules reconnection attempts.
- `close()`: Closes the socket. For use in development (esp8266) to prevent `LmacRxBlk:1` failures
  if an application raises an exception or is terminated with ctrl-C.
- `broker_up()`: Unless data was received in the last second it issues an MQTT ping and waits
  for a response. If it times out (`response_time` exceeded) with no response it
  returns `False` otherwise it returns `True`.
- `wan_ok(packet)`: Returns `True` if internet connectivity is available, else `False`. It first
  checks current WiFi and broker connectivity. If present, it sends a DNS query
  to '8.8.8.8' and checks for a valid response.

## References

[mqtt introduction](http://mosquitto.org/man/mqtt-7.html)  
[mosquitto server](http://mosquitto.org/man/mosquitto-8.html)  
[mosquitto client publish](http://mosquitto.org/man/mosquitto_pub-1.html)  
[mosquitto client subscribe](http://mosquitto.org/man/mosquitto_sub-1.html)  
[MQTT 3.1.1 spec](http://docs.oasis-open.org/mqtt/mqtt/v3.1.1/os/mqtt-v3.1.1-os.html#_Toc398718048)  
[python client for PC's](https://www.eclipse.org/paho/clients/python/)  
