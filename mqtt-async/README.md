# MicroPython Asynchronous MQTT

The `mqtt_async` library implements the MQTT 3.1.1 protocol with support for
QoS 0 and QoS 1 and using Micropython's new (in 2020) built-in asyncio / uasyncio.
The implementation in this repository is a rewrite inspired by and largely API compatible with
[Peter Hinch's version](https://github.com/peterhinch/micropython-mqtt).

Some of the special features of this library:
- Fully integrated with the new MicroPython built-in uasyncio.
- Supports QoS 0 and QoS 1 with automatic retries when sending QoS 1 messages.
- Automatic keep-alive messages and disconnect/reconnect when the connection to the broker ceases to
  function.
- Disconnect/reconnect first acts at the TCP connection level but then moves to reconnect Wifi.
- Publishing messages at QoS 1 can be asynchronous such that the application can proceed before an
  ACK is received from the broker.

Feature that need a little more work:
- Support starting with a clean session or resuming from a previous session.
- Support TLS.

## Getting Started

This README assumes basic familiarity with MQTT and MicroPython.

### Installation

This library **requires** the use of the new `uasyncio` module built-into MicroPythonA as of the
merge of [PR 5796](https://github.com/micropython/micropython/pull/5796) on March 25th 2020. In
terms of MP releases this will mean V1.13 or greater.

```
import upip
upip.install('micropython-mqtt')
upip.install('micropython-logging')
```

Alternatively, you can:
- copy the `mqtt_async.py` file to your board, e.g., `pyboard.py -f cp mqtt_async.py :`
- cross-compile the library to an mpy file and upload that
- skip `micropython-logging` as there is a fall-back

### Hello World

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

## Implementation Specifics

### Hardware platforms.

This library has been tested with Micropython compiled with ESP-IDFv4 on an esp32.
MP with ESP-IDFv3 has not been tested.

This library contains code to handle the esp8266 but it has not been tested, except to determine
that the library has to be frozen into the firmware in order to be usable. (This is the same
situation as with `mqtt_as`.)  The author does not expect to test the esp8266 but will accept PRs to
fix any issues.

### Compatibility with the original mqtt_as

The API of MQTTClient between the original `mqtt_as` and the new `mqtt_async` is largely the same,
see below for changes.
The implementation, however, has been modified significantly:

1. Support sending streams of MQTT messages at QoS=1 without blocking for an ACK after each message.
   This allows streaming of data using relatively small messages at high data rates.
2. Almost full test coverage via automated tests. The lower-level protocol class is tested on a
   Micropython board against a real broker to ensure that the protocol works and that failures are
   reported appropriately.
   The higher-level client class is tested on linux using a simulated protocol class to test
   failures and retransmissions.
3. The implementation is completely reorganized to facilitate automated testing, to correctly handle
   retransmissions across connection reconnects and to enable the implementation of the streaming.
   Specifically, the implementation is split such that a lower-level class (`MQTTProto`) implements
   the protocol on a single socket and a higher-level class (`MQTTClient`) implements the
   reconnection and retransmission logic.
4. Messages that normally fit into a TCP packet get sent as a single packet on the wire to reduce
   overall overhead thereby improving performance.
4. Retransmission of messages on an existing TCP connection is eliminated because it is totally
   pointless given that TCP implements a reliable stream (it is impossible for an application to
   receive data that was sent on a connection after previous data got "lost" or "corrupted").
   Instead, if no ACK is received the retransmission uses a fresh connection from the get-go.
5. Correctly retransmit packets on a fresh connection using the original PID (packet ID) to
   avoid unnecessary duplicate packets. The original implementation used a fresh PID due to a bug
   that made it look like Mosquitto wasn't accepting the retransmission.
6. When reconnecting, first do so at the TCP level without tearing Wifi down to minimize the
   disruption, only disconnect/reconnect Wifi if the TCP reconnect doesn't work.
7. Eliminate `clean_init` config param and only use clean config param, see below.
8. Structure imports and work-arounds such that `mqtt_async` can be used in CPython and tests can
   use `pytest`.
9. Use the standard logging facility instead of ad-hoc debug messages.

#### API incompatibilities

- the `subs_cb` callback has 4 parameters, adding a qos parameter.
- the `will` config has been changed from a tuple to an `MQTTMessage`.
- the semantics of the `clean` config have been changed and `clean_init` has been dropped.
- a number of methods have been dropped (isconnected, close, ...)
- the `ssl` config has been dropped: set the `ssl_params` config to `{}` if nothing special is
  required.
- TODO: determine others

### Streaming data using small messages

In general MQTT supports sending a long stream of data by breaking it up into small messages that
are all sent to the same topic using QoS=1. The protocol guarantees in-order delivery of those
messages such that the receiver can easily process them and only needs to check for duplicates, this
is codified in [section 4.6 of the MQTT 3.1.1 spec](http://docs.oasis-open.org/mqtt/mqtt/v3.1.1/os/mqtt-v3.1.1-os.html#_Toc398718105).

When sending messages using `publish()` the default is to send the message and then block to wait
for an MQTT-level ACK. This wait has a significant impact on rate at which a stream of small
messages can be transmitted.
The implementation here adds a `sync` parameter to `publish()` which, if set to `False`, omits
the wait allowing the application to explicitly verify whether an ACK has been received later.

In order to send N messages in-order reliably an application can send the first N-1 messages
using `qos=1` and `sync=False` and then send the last message using `qos=1` and`sync=True`.
Once the last publish completes the broker has received all messages in order.
(Note that the in-order guarantee only applies if the N messages are sent to one and the same topic.)

### How to use the clean session flag

FIXME: the implementation still needs some tweaking...

The clean session flag specifies whether the broker should retain state between connections for
a specific client ID.
The state includes subscriptions and pending/queued messages.
Something that is slighly confusing is that if a connection specifies `clean=True` then the state
is cleared before *and* after the connection.
As a result the two primary modes of operation should be:
1. Clients that don't need state to be preserved should connect with `clean=True` and must re-issue
   all subscriptions in the `connect_coro`. Messages queued at the broker when a connection ends and
   a new one is established, which happens automatically in MQTTClient when there is a failure, will
   be lost.
2. Clients that do need state to be preserved should always connect with `clean=False`. The
   confusing part is that it is often desirable to clean the state on cold-boot or when a new
   software version is loaded in order to avoid having incorrect subscriptions active that are no
   longer relevant. In order to achieve that the client should connect with `clean=True`,
   immediately disconnect, and then reconnect with `clean=False` and proceed.

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
Wifi, then run something like `pyboard <options> -f cp mqtt_async.py :` followed by
`pyboard <options> test_proto.py`.

With the broker info fixed-up in `test_proto.py` it is also possible to run
`pytest --cov=mqtt_async --cov-report=html` to run all tests and produce a code coverage report in
`./htmlcov`. As of this writing the coverage is in the high eighties percent.

`test-tcp.py` is a low-level test that can be run manually on a board to test the behavior of the
socket library and networking stack. It requires simulating failures manually for example using
iptables on the broker end to block the flow of packets. The results then require manual
interpretation, but the end goal is to ensure that the behavior of socket operations under failure
is understood. Comments at the start of the file capture some of the observations made on the esp32.

`test-clean.py` is also a manual test that was used to ascertain the behavior of the clean flag when
creating a session. It is not useful as a unit test and kept for posteriority...


## MQTTClient class

### `__init__(config)`

The constructor initializes an MQTTClient instance with the provided configuration.
The config must be an instance of the MQTTConfig class and is typically put together
by modifying the default `mqtt_async.config` instance. The MQTTConfig fields can be accessed
either as class fields or using the `['field_name']` map syntax.

The following MQTTConfig fields must be set:
- `server`: [`None`] MQTT broker hostname or IP address, no default.
- `connect_coro`: `async def` function that is run when the first MQTT connection is established, it
  should subscribe to the desired topics, default: None.
- `subs_cb`: `def` or `async def` function that is run when a message arrives on a topic, default:
  None.

The following MQTTConfig fields are optional but recommended:
- `ssid`: WiFi SSID to connect or reconnect Wifi in case of failure, default: None.
- `wifi_pw`: WiFi password, default: None.
- Note that the esp8266 does not require the wifi info if it has previously connected as it remebers
  the last used credentials.

Optional MQTTConfig fields:
- `ssl_params`: enable TLS with the provided parameters, default: None (disable TLS/SSL). *Not yet
  supported*
- `connect_coro`: `async def` function that is run with a `status` parameter when an MQTT connection
  starts (`status=True`) or ends (`status=False`), default: None.
- `port`: MQTT broker port, default: 0 which means 8883 if TLS is used, else 1883.
- `client_id`: MQTT client id, must be a `bytes` instance, default: `machine.unique_id()` in hex.
- `user`: MQTT credentials (if required).
- `password` [`''`] MQTT password for `user`.
- `clean`: start a clean MQTT session, see above for a discussion, default: False.
- `response_time`: Time in seconds given to the broker to respond before a connection is restarted,
  applies to sub-suback, pub-puback, and ping-pingresp intervals. Default: 10.
- `keepalive`: Time in seconds before broker regards client as having died and sends a last-will
  message. Not relevant if no `will` is set.
- `will`: `MQTTMessage` instance with last-will message, can be set using
  `config.set-last-will(topic, message, retain, qos)`, default: None.
- `interface`: should be `network.WLAN(network.STA_IF)` or `WLAN(network.AP_IF)`, default: `STA_IF`.

### `connect()` (async)

No args. Connects to the specified broker. The application should call
`connect` once on startup. If this fails (due to WiFi or the broker being
unavailable) an `OSError` will be raised. Subsequent reconnections after
outages are handled automatically.

### `publish(topic, msg, retain=False, qos=0, sync=True)` (async)

Publishes the messages with the provided parameters. Topic and msg should be `bytes` but `str` is
also accepted and automatically encoded.

If connectivity is not OK `publish` will block until a connection is established.

For QoS 0, `publish` sends the message and returns immediately.

For QoS 1, `publish` sends the message then it waits for any _previously_ outstanding ACK.
If `sync=False` it then returns (i.e. doesn't wait for an ACK for the just-sent message).
If `sync=True` it waits for the just-sent message to be ACKed and then returns.
If the connection gets dropped at any point in time `publish` automatically retransmits any unACKed
message.

### `subscribe(topic, qos=0)` (async)

Subscribes to a topic and awaits an ACK from the broker.
The `qos` parameter specifies at which QoS level the messages will be transmitted by the broker.

Subscriptions should generally be made in the `connect_coro` specified in the config.

If connectivity is not OK `publish` will block until a connection is established.

When messages arrive on subscriptions the `subs_cb` is called with the topic, message, retain flag,
and QoS level as parameters. The `subs_cb` may be a plain function or an `async def` function. For
incoming QoS=1 messages an acknowledgment is sent to the broker once `subs_cb` returns.

### `disconnect()` (async)

Sends a disconnect message to the broker and closes the connection. Sending the disconnect message
suppresses the last-will message in the broker.

It is not possible to reconnect an `MQTTClient` after calling disconnect: create a fresh instance
instead.

### Logging

`mqtt_async` uses the standard logging facility with a logger called `mqtt_async`.
By default this seems to print INFO messages and higher.
If the `logging` module is not available some simple stand-ins are used.

A simple way to tune the logging from your application is:

```
import logging
logging.basicConfig(level=logging.DEBUG)
```
Use the `WARNING` level to suppress more messages.

### Timeouts

The `MQTTClient` functions do not use timeouts, that is, if the broker does not respond (possibly
due to there being no connectivity) calls will block forever. Use `asyncio.wait_for()` to introduce
timeouts if desired.

### Not supported

The following methods from `mqtt_as` are not supported:
- `isconnected():` returns `True` if connectivity is OK otherwise it returns `False` and schedules
reconnection attempts.
- `close()`: Closes the socket. For use in development to prevent `LmacRxBlk:1` failures if
an application raises an exception or is terminated with ctrl-C.
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
[Unofficial MQTT FAQ](https://forum.micropython.org/viewtopic.php?f=16&t=2239)
