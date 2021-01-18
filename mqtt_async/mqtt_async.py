# mqtt_async.py MQTT implementation for MicroPython using the new uasyncio built into MP in 2020.
# Copyright © 2020 by Thorsten von Eicken.
#
# Loosely based on a version of mqtt_as by Peter Hinch
# (which had various improvements contributed by Kevin Köck).
# (C) Copyright Peter Hinch 2017-2019.
#
# Released under the MIT licence.
# See the README.md in this directory for implementaion and usage details.

# The imports below are a little tricky in order to support operation under Micropython as well as
# Linux CPython. The latter is used for tests.

import socket
import struct
import sys
from binascii import hexlify
from errno import EINPROGRESS

try:
    # imports used with Micropython
    # on Unix might need to set MICROPYPATH env var to locate extmod
    from micropython import const
    from time import ticks_ms, ticks_diff
    import uasyncio as asyncio

    async def open_connection(addr, ssl):
        return (await asyncio.open_connection(addr[0], addr[1], ssl=ssl))[0]

    try:
        from machine import unique_id

        import network

        STA_IF = network.WLAN(network.STA_IF)
    except ImportError:
        # work-arounds on unix micropython
        from unix_fix import *

    def is_awaitable(f):
        return f.__class__.__name__ == "generator"


except ImportError:
    # Imports used with CPython (moved to another file so they don't appear on MP HW)
    from cpy_fix import *

try:
    import logging

    log = logging.getLogger(__name__)
except ImportError:

    class Logger:  # please upip.install('logging')
        def debug(self, msg, *args):
            pass

        def info(self, msg, *args):
            print(msg % (args or ()))

        def warning(self, msg, *args):
            print(msg % (args or ()))

    log = Logger()

# Timing parameters and constants

# Response time of the broker to requests, such as pings, before MQTTClient deems the connection
# to be broken and tries to reconnect. MQTTClient issues an explicit ping if there is no
# outstanding request to the broker for half the response time. This means that if the connection
# breaks and there is no outstanding request it could take up to 1.5x the response time until
# MQTTClient notices.
# Specified in MQTTConfig.response_time, suggested to be in the range of 60s to a few minutes.

# Connection time-out when establishing an MQTT connection to the broker:
# Specified in MQTTConfig.conn_timeout in seconds

# Keepalive interval with broker per MQTT spec. Determines at what point the broker sends the last
# will message. Pretty much irrelevant if no last-will message is set. This interval must be
# greater than 2x the response time.
# Specified in MQTTConfig.keepalive

# Default long delay in seconds when waiting for a connection to be re-established.
# Can be overridden in tests to make things go faster
_CONN_DELAY = const(1)

# Error strings used with OSError(-1, ...) for internally raised errors.
CONN_CLOSED = "Connection closed"
CONN_TIMEOUT = "Connection timed out"
PROTO_ERROR = "Protocol error"
CONN_ERRS = ["inv proto vers", "client_id rejected", "srv down", "user/pass malformed", "not auth"]

# config holds the default values for all configuration items.
config = {
    "client_id": hexlify(unique_id()),
    "server": None,
    "port": 0,
    "user": None,
    "password": b"",
    "response_time": 10,  # in seconds
    "keepalive": 600,  # in seconds, only sent if self.will != None
    "ssl_params": None,
    "interface": STA_IF,
    "clean": True,
    "will": None,  # last will message, must be MQTTMessage
    "subs_cb": lambda *_: None,  # callback when message arrives for a subscription
    "wifi_coro": None,  # notification when MQTT connects/disconnects
    "connect_coro": None,  # notification when MQTT first becomes ready
    "ssid": None,
    "wifi_pw": None,
    # The following are not currently supported:
    # "sock_cb"         : None,            # callback for esp32 socket to allow bg operation
    # "listen_interval" : 0,               # Wifi listen interval for power save
    # "conn_timeout"    : 120,             # in seconds
}


# set_last_will records the last will into the config, the last will is transmitted to the broker
# on connect
def set_last_will(config, topic, message, retain=False, qos=0):
    _qos_check(qos)
    if not topic:
        raise ValueError("empty topic")
    config["will"] = MQTTMessage(topic, message, retain, qos)


# _qos_check is a utility function to check the qos value
def _qos_check(qos):
    if not (qos == 0 or qos == 1):
        raise ValueError("unsupported qos")


class MQTTMessage:
    def __init__(self, topic, message, retain=False, qos=0, pid=None):
        # if qos and pid is None:
        #    raise ValueError('pid missing')
        _qos_check(qos)
        if isinstance(topic, str):
            topic = topic.encode()
        if isinstance(message, str):
            message = message.encode()
        self.topic = topic
        self.message = message
        self.retain = retain
        self.qos = qos
        self.pid = pid


# MQTTproto implements the MQTT protocol on the basis of a good connection on a single connection.
# A new class instance is required for each new connection.
# Connection failures and EOF cause an OSError exception to be raised.
# The operation of MQTTProto is generally blocking and relies on an external watchdog to call
# disconnect() if the connection is evidently stuck. Note that this applies to connect() as well!
class MQTTProto:

    # __init__ creates a new connection based on the config.
    # The list of init params is lengthy but it clearly spells out the dependencies/inputs.
    # The _cb parameters are for publish, puback, and suback packets.
    def __init__(self, subs_cb, puback_cb, suback_cb, pingresp_cb, sock_cb=None):
        # Store init params
        self._subs_cb = subs_cb
        self._puback_cb = puback_cb
        self._suback_cb = suback_cb
        self._pingresp_cb = pingresp_cb
        self._sock_cb = sock_cb
        # Init key instance vars
        self._sock = None
        self._lock = asyncio.Lock()
        self.last_ack = 0  # last ACK received from broker
        self._read_buf = b""

    # connect initiates a connection to the broker at addr.
    # Addr should be the result of a gethostbyname (typ. an ip-address and port tuple).
    # The clean parameter corresponds to the MQTT clean connection attribute.
    # Connect waits for the connection to get established and for the broker to ACK the connect
    # packet.  It raises an OSError if the connection cannot be made.
    # Reusing an MQTTProto for a second connection is not recommended.
    async def connect(
        self, addr, client_id, clean, user=None, pwd=None, ssl=None, keepalive=0, lw=None
    ):
        if lw is None:
            keepalive = 0
        log.info("Connecting to %s id=%s clean=%d", addr, client_id, clean)
        log.debug("user=%s passwd-len=%s ssl=%s", user, pwd and len(pwd), ssl)
        try:
            # in principle, open_connection returns a (reader,writer) stream tuple, but in MP it
            # really returns a bidirectional stream twice, so we cheat and use only one of the
            # tuple values for everything.
            self._sock = await open_connection(addr, ssl)
        except OSError as e:
            if e.args[0] != EINPROGRESS:
                log.info("OSError in open_connection: %s", e)
                raise
        await asyncio.sleep_ms(10)  # sure sure this is needed...
        # Construct connect packet
        premsg = bytearray(b"\x10\0\0\0\0")  # Connect message header
        msg = bytearray(b"\0\x04MQTT\x04\0\0\0")  # Protocol 3.1.1
        if isinstance(client_id, str):
            client_id = client_id.encode()
        sz = 10 + 2 + len(client_id)
        msg[7] = (clean & 1) << 1
        if user is not None:
            if isinstance(user, str):
                user = user.encode()
            if isinstance(pwd, str):
                pwd = pwd.encode()
            sz += 2 + len(user) + 2 + len(pwd)
            msg[7] |= 0xC0
        if keepalive:
            msg[8] |= (keepalive >> 8) & 0x00FF
            msg[9] |= keepalive & 0x00FF
        if lw is not None:
            sz += 2 + len(lw.topic) + 2 + len(lw.message)
            msg[7] |= 0x4 | (lw.qos & 0x1) << 3 | (lw.qos & 0x2) << 3
            msg[7] |= lw.retain << 5
        i = self._write_varint(premsg, 1, sz)
        # Write connect packet to socket
        try:
            if self._sock is None:
                await asyncio.sleep_ms(100)  # esp32 glitch
            await self._as_write(premsg[:i], drain=False)
            await self._as_write(msg, drain=False)
            await self._send_str(client_id, drain=False)
            if lw is not None:
                await self._send_str(lw.topic)  # let it drain in case message is long
                await self._send_str(lw.message)
            if user is not None:
                await self._send_str(user, drain=False)
                await self._send_str(pwd, drain=False)
            try:
                await self._as_write(b"")  # cause drain
            except OSError as e:
                log.info("OSError in write: %s", e)
                raise
            # Await CONNACK
            # read causes ECONNABORTED if broker is out
            try:
                resp = await self._as_read(4)
            except OSError as e:
                log.info("OSError in read: %s", e)
                raise
            if resp[0] != 0x20 or resp[1] != 0x02:
                raise OSError(-1, "Bad CONNACK")
            if resp[3] != 0:
                if resp[3] < 6:
                    raise OSError(-1, "CONNECT refused: " + CONN_ERRS[resp[3] - 1])
                else:
                    raise OSError(-1, "CONNECT refused")
        except Exception:
            self._sock.close()
            await self._sock.wait_closed()
            raise
        self.last_ack = ticks_ms()
        # gc.collect()
        log.debug("Connected")  # Got CONNACK

    # ===== Helpers

    # _as_read reads n bytes from the socket in a blocking manner using asyncio and returns them as
    # bytes. On error *and on EOF* it raises an OSError.
    # There is no time-out, instead, as_read relies on the socket being closed by a watchdog.
    # _as_read buffers a bunch of bytes because calling self.sock._read takes 4-5ms minimum and
    # _read_msg does a good number of very short reads.
    async def _as_read(self, n):
        # Note: uasyncio.Stream.read returns short reads
        while self._sock:
            # read missing amt
            missing = n - len(self._read_buf)
            if missing > 0:
                if missing < 128:
                    missing = 128
                got = await self._sock.read(missing)
                if got is None:
                    continue
                if len(got) == 0:
                    raise OSError(-1, CONN_CLOSED)
                self._read_buf += got
                missing = n - len(self._read_buf)
            # got enough?
            if missing == 0:
                res = self._read_buf
                self._read_buf = b""
                return res
            if missing < 0:
                res = self._read_buf[:n]
                self._read_buf = self._read_buf[n:]
                return res
        raise OSError(-1, CONN_CLOSED)

    # _as_write writes n bytes to the socket in a blocking manner using asyncio. On error or EOF
    # it raises an OSError.
    # There is no time-out, instead, as_write relies on the socket being closed by a watchdog.
    async def _as_write(self, bytes_wr, drain=True):
        if self._sock is None:
            raise OSError(-1, CONN_CLOSED)
        if bytes_wr != b"":
            self._sock.write(bytes_wr)
        if drain:
            await self._sock.drain()

    # _send_str writes a variable-length string to the socket, prefixing the chars by a 16-bit
    # length
    async def _send_str(self, s, drain=True):
        await self._as_write(struct.pack("!H", len(s)), drain=False)
        await self._as_write(s, drain)

    # _read_varint reads a varint used for lengths in MQTT
    async def _read_varint(self):
        n = 0
        sh = 0
        while 1:
            res = await self._as_read(1)
            b = res[0]
            n |= (b & 0x7F) << sh
            if not b & 0x80:
                return n
            sh += 7

    # _write_varint writes 'value' into 'array' starting at offset 'index'. It returns the index
    # after the last byte placed into the array. Only positive values are handled.
    def _write_varint(self, array, index, value):
        while value > 0x7F:
            array[index] = (value & 0x7F) | 0x80
            value >>= 7
            index += 1
        array[index] = value
        return index + 1

    # ===== Public functions

    # ping sends a ping packet
    async def ping(self):
        async with self._lock:
            await self._as_write(b"\xc0\0")

    # disconnect tries to send a disconnect packet and then closes the socket
    # Trying to send a disconnect as opposed to just closing the socket is important because the
    # broker sends a last-will message if the socket is just closed.
    async def disconnect(self):
        try:
            async with self._lock:
                if self._sock is None:
                    return
                self._sock.write(b"\xe0\0")
                await asyncio.wait_for(
                    self._sock.drain(), 0.2
                )  # 200ms to make sure ipoll gets a chance
        except Exception:
            pass
        if self._sock is not None:
            self._sock.close()
            await self._sock.wait_closed()
        self._sock = None

    def isconnected(self):
        self._sock is not None

    # publish writes a publish message onto the current socket. It raises an OSError on failure.
    # If qos==1 then a pid must be provided.
    # msg.topic and msg.message must be byte arrays, or equiv.
    async def publish(self, msg, dup=0):
        # calculate message length
        mlen = len(msg.message)
        sz = 2 + len(msg.topic) + mlen
        if msg.qos > 0:
            sz += 2  # account for pid
        if sz >= 2097152:
            raise ValueError("message too long")
        # construct packet: if possible, put everything into a single large bytearray so a single
        # socket send call can be made resulting in a single packet.
        hdrlen = 4 + 2 + len(msg.topic) + 2
        single = hdrlen + mlen <= 1440  # slightly conservative MSS
        if single:
            pkt = bytearray(hdrlen + mlen)
        else:
            pkt = bytearray(hdrlen)
        pkt[0] = 0x30 | msg.qos << 1 | msg.retain | dup << 3
        length = self._write_varint(pkt, 1, sz)
        struct.pack_into("!H", pkt, length, len(msg.topic))
        length += 2
        pkt[length: length + len(msg.topic)] = msg.topic
        length += len(msg.topic)
        if msg.qos > 0:
            struct.pack_into("!H", pkt, length, msg.pid)
            length += 2
        # send header and body
        async with self._lock:
            if single:
                pkt[length:] = msg.message
                await self._as_write(pkt)
            else:
                await self._as_write(pkt[:length])
                await self._as_write(msg.message)

    # subscribe sends a subscription message.
    async def subscribe(self, topic, qos, pid):
        if (qos & 1) != qos:
            raise ValueError("invalid qos")
        pkt = bytearray(b"\x82\0\0\0")
        if isinstance(topic, str):
            topic = topic.encode()
        struct.pack_into("!BH", pkt, 1, 2 + 2 + len(topic) + 1, pid)
        async with self._lock:
            await self._as_write(pkt, drain=False)
            await self._send_str(topic, drain=False)
            await self._as_write(qos.to_bytes(1, "little"))

    #   # unsubscribe sends an unsubscription message.
    #   async def unsubscribe(self, topic, pid):
    #       pkt = bytearray(b"\xA2\0\0\0")
    #       if isinstance(topic, str):
    #           topic = topic.encode()
    #       struct.pack_into("!BH", pkt, 1, 2 + 2 + len(topic), pid)
    #       async with self._lock:
    #           await self._as_write(pkt, drain=False)
    #           await self._send_str(topic)

    # Read a single MQTT message and process it.
    # Subscribed messages are delivered to a callback previously set by .setup() method.
    # Other (internal) MQTT messages processed internally.
    # Called from ._handle_msg().
    async def read_msg(self):
        # t0 = ticks_ms()
        res = await self._as_read(1)
        # We got something, dispatch based on message type
        op = res[0]
        # log.debug("read_msg op=%x", op)
        if op == 0xD0:  # PINGRESP
            await self._as_read(1)
            self.last_ack = ticks_ms()
            self._pingresp_cb()
        elif op == 0x40:  # PUBACK: remove pid from unacked_pids
            sz = await self._as_read(1)
            if sz != b"\x02":
                raise OSError(-1, PROTO_ERROR, "puback", sz)
            rcv_pid = await self._as_read(2)
            pid = rcv_pid[0] << 8 | rcv_pid[1]
            self.last_ack = ticks_ms()
            self._puback_cb(pid)
        elif op == 0x90:  # SUBACK: flag pending subscribe to end
            resp = await self._as_read(4)
            pid = resp[2] | (resp[1] << 8)
            # print("suback", resp[3])
            self.last_ack = ticks_ms()
            self._suback_cb(pid, resp[3])
        elif (op & 0xF0) == 0x30:  # PUB: dispatch to user handler
            sz = await self._read_varint()
            topic_len = await self._as_read(2)
            topic_len = (topic_len[0] << 8) | topic_len[1]
            topic = await self._as_read(topic_len)
            # log.debug("topic:%s", topic)
            sz -= topic_len + 2
            retained = op & 0x1
            dup = op & 0x8
            qos = (op >> 1) & 3
            pid = None
            if qos:  # not QoS=0 -> got pid
                pid = await self._as_read(2)
                pid = pid[0] << 8 | pid[1]
                sz -= 2
            # log.debug("pid:%s sz=%d", pid, sz)
            if sz < 0:
                raise OSError(-1, PROTO_ERROR, "pub sz", sz)
            else:
                msg = await self._as_read(sz)
            # Dispatch to user's callback handler
            log.debug("dispatch pub %s pid=%s qos=%d", topic, pid, qos)
            # t1 = ticks_ms()
            try:
                cb = self._subs_cb(topic, msg, bool(retained), qos, dup)
                if is_awaitable(cb):
                    await cb  # handle _subs_cb being coro
            except Exception as e:
                log.exc(e, "exception in handler")
            # t2 = ticks_ms()
            # Send PUBACK for QoS 1 messages
            if qos == 1:
                pkt = bytearray(b"\x40\x02\0\0")
                struct.pack_into("!H", pkt, 2, pid)
                async with self._lock:
                    await self._as_write(pkt)
            elif qos == 2:
                raise OSError(-1, "QoS=2 not supported")
            # log.debug("read_msg: read:{} handle:{} ack:{}".format(ticks_diff(t1, t0),
            #    ticks_diff(t2, t1), ticks_diff(ticks_ms(), t2)))
        else:
            raise OSError(-1, PROTO_ERROR, "bad op", op)
        return op >> 4


# -----------------------------------------------------------------------------------------

PING_PID = const(100000)  # fake pid used in handling of ping acks


# MQTTClient class.
class MQTTClient:
    def __init__(self, conf):
        # handle config
        self._c = config.copy()
        self._c.update(conf)
        # config last will and keepalive
        if self._c["will"] is None:
            self._c["keepalive"] = 0  # no point setting MQTT keepalive if there's no lw
        elif not isinstance(self._c["will"], MQTTMessage):
            raise ValueError("will must be MQTTMessage")
        if self._c["keepalive"] >= 65536:
            raise ValueError("invalid keepalive")
        if self._c["keepalive"] > 0 and self._c["keepalive"] < self._c["response_time"] * 2:
            raise ValueError("keepalive <2x response_time")
        # config server and port
        if self._c["port"] == 0:
            self._c["port"] = 8883 if self._c["ssl_params"] else 1883
        if self._c["server"] is None:
            raise ValueError("no server")
        # init instance vars
        self._proto = None
        self._MQTTProto = MQTTProto  # reference to class, override for testing
        self._addr = None
        self._lastpid = 0
        self._unacked_pids = {}  # PUBACK and SUBACK pids awaiting ACK response
        self._state = 0  # 0=init, 1=has-connected, 2=disconnected=dead
        self._conn_keeper = None  # handle to persistent keep-connection coro
        self._prev_pub = None  # MQTTMessage of as yet unacked async pub
        self._prev_pub_proto = None  # self._proto used for as yet unacked async pub
        # misc
        # if platform == "esp8266":
        #    import esp
        #    esp.sleep_type(0)  # Improve connection integrity at cost of power consumption.

    async def wifi_connect(self):
        log.info("connecting wifi")
        s = self._c["interface"]
        # if platform == "esp8266":
        #    if s.isconnected():  # 1st attempt, already connected.
        #        return
        #    s.active(True)
        #    s.connect()  # ESP8266 remembers connection.
        #    for _ in range(60):
        #        if (
        #            s.status() != network.STAT_CONNECTING
        #        ):  # Break out on fail or success. Check once per sec.
        #            break
        #        await asyncio.sleep(_CONN_DELAY)
        #    if (
        #        s.status() == network.STAT_CONNECTING
        #    ):  # might hang forever awaiting dhcp lease renewal or something else
        #        s.disconnect()
        #        await asyncio.sleep(_CONN_DELAY)
        #    if (
        #        not s.isconnected()
        #        and self._c["ssid"] is not None
        #        and self._c["wifi_pw"] is not None
        #    ):
        #        s.connect(self._c["ssid"], self._c["wifi_pw"])
        #        while (
        #            s.status() == network.STAT_CONNECTING
        #        ):  # Break out on fail or success. Check once per sec.
        #            await asyncio.sleep(_CONN_DELAY)
        # elif self._c["ssid"]:
        if self._c["ssid"]:
            s.active(True)
            # log.debug("Connecting, li=%d", self._c["listen_interval"])
            s.connect(self._c["ssid"], self._c["wifi_pw"])
            #  s.connect(self._c["ssid"], self._c["wifi_pw"],
            #            listen_interval=self._c["listen_interval"])
            if sys.platform == "pyboard":  # Doesn't yet have STAT_CONNECTING constant
                while s.status() in (1, 2):
                    await asyncio.sleep(_CONN_DELAY)
            else:
                while s.status() == network.STAT_CONNECTING:  # Break out on fail or success.
                    await asyncio.sleep_ms(200)
        else:
            raise OSError(-1, "no SSID to connect to Wifi")

        if not s.isconnected():
            log.warning("Wifi failed to connect")
            raise OSError(-1, "Wifi failed to connect")

    def _dns_lookup(self):
        new_addr = socket.getaddrinfo(self._c["server"], self._c["port"])
        if len(new_addr) > 0 and len(new_addr[0]) > 1:
            self._addr = new_addr[0][-1]
        log.debug("DNS %s->%s", self._c["server"], self._addr)

    async def connect(self):
        if self._state > 1:
            raise ValueError("cannot reuse")
        clean = False
        # deal with wifi and dns
        if not self._c["interface"].isconnected():
            await self.wifi_connect()
        if self._state == 0:
            self._dns_lookup()  # DNS is blocking, do it only the first time around
            clean = self._c["clean"]
        # actually open a socket and connect
        proto = self._MQTTProto(
            self._c["subs_cb"], self._got_puback, self._got_suback, self._got_pingresp
        )
        # FIXME: need to use a timeout here!
        await proto.connect(
            self._addr,
            self._c["client_id"],
            clean,
            user=self._c["user"],
            pwd=self._c["password"],
            ssl=self._c["ssl_params"],
            keepalive=self._c["keepalive"],
            lw=self._c["will"],
        )  # raises on error
        # update state
        if self._state == 0:
            self._state = 1
            # this is the first time we connect, if we asked for a clean session we need to
            # disconnect and reconnect with clean=False so the broker doesn't drop all the state
            # when we get our first disconnect due to network issues
            if clean:
                await proto.disconnect()
                return await self.connect()
        elif self._state > 1:
            await self.disconnect()  # whoops, someone called disconnect() while we were connecting
            raise OSError(-1, "disconnect while connecting")
        # First thing, retransmit if there is an async packet outstanding and it has not been acked
        m = self._prev_pub
        if m is not None and m.pid in self._unacked_pids:
            log.warning("repub->%s qos=%d pid=%s", m.topic, m.qos, m.pid)
            self._prev_pub_proto = proto
            await proto.publish(m, dup=1)
        self._proto = proto
        # If we get here without error broker/LAN must be up.
        loop = asyncio.get_event_loop()
        # Start background coroutines that run until the user calls disconnect
        if self._conn_keeper is None:
            self._conn_keeper = loop.create_task(self._keep_connected())
        # Start background coroutines that quit on connection fail
        loop.create_task(self._handle_msgs(self._proto))
        loop.create_task(self._keep_alive(self._proto))
        # Notify app that we're connected and ready to roll
        if self._c["connect_coro"] is not None:
            loop.create_task(self._c["connect_coro"](self))
            self._c["connect_coro"] = None  # FIXME: nasty...
        # Notify app that broker is connected
        if self._c["wifi_coro"] is not None:
            loop.create_task(self._c["wifi_coro"](True))  # Notify app that Wifi is up
        # log.debug("connected")

    async def disconnect(self):
        self._state = 2  # dead - do not reconnect
        if self._proto is not None:
            await self._proto.disconnect()  # should we do a create_task here?
        self._proto = None

    # start the connection process without blocking
    def start(self):
        if self._state > 0:
            raise ValueError("cannot reuse")
        loop = asyncio.get_event_loop()
        self._conn_keeper = loop.create_task(self._keep_connected())

    # ===== Manage PIDs and ACKs
    # self._unacked_pids is a hash that contains unacked pids. Each hash value is a list, the first
    # element of which is an asycio.Event that gets set when an ack comes in. The second element is
    # the return qos value in the case of a subscribe and is None in the case of a publish.

    def _newpid(self):
        self._lastpid += 1
        if self._lastpid > 65535:
            self._lastpid = 1
        return self._lastpid

    # _got_puback handles a puback by removing the pid from those we're waiting for
    def _got_puback(self, pid):
        if pid in self._unacked_pids:
            self._unacked_pids[pid][0].set()
            del self._unacked_pids[pid]

    def _got_pingresp(self):
        self._got_puback(PING_PID)

    # _got_suback handles a suback by placing the response into the _unacked_pid list
    # _await_pid will have to delete the item from the list
    def _got_suback(self, pid, actual_qos):
        if pid in self._unacked_pids:
            self._unacked_pids[pid][1] = actual_qos
            self._unacked_pids[pid][0].set()

    # _await_pid waits until the broker ACKs a pub or sub message, or it times out.
    # If the element of the self._unacked_pids list still exists, it returns the second element.
    async def _await_pid(self, pid):
        if pid not in self._unacked_pids:
            return None
        # wait for ACK to come in with a timeout # TODO: calculate timeout based on time sent
        try:
            if not self._unacked_pids[pid][0].is_set():
                await asyncio.wait_for(self._unacked_pids[pid][0].wait(), self._c["response_time"])
        except asyncio.TimeoutError:
            raise OSError(-1, CONN_TIMEOUT)
        # return second list element -- this only happens for subscribe acks
        if pid in self._unacked_pids:
            ret = self._unacked_pids[pid][1]
            del self._unacked_pids[pid]
            return ret
        else:
            return None

    # ===== Background coroutines

    # Launched by connect. Runs until connectivity fails. Checks for and
    # handles incoming messages.
    async def _handle_msgs(self, proto):
        try:
            while True:
                await proto.read_msg()
        except OSError as e:
            await self._reconnect(proto, "read_msg", e)

    # ping and wait for response, wrapped in a coroutine to be used in asyncio.wait_for()
    async def _ping_n_wait(self, proto):
        await proto.ping()
        await self._await_pid(PING_PID)

    # Keep connection alive MQTT spec 3.1.2.10 Keep Alive.
    # Runs until ping failure or no response in keepalive period.
    async def _keep_alive(self, proto):
        rt_ms = self._c["response_time"] * 1000
        try:
            while proto.isconnected():
                dt = ticks_diff(ticks_ms(), proto.last_ack)
                if dt > rt_ms:
                    # it's time for another ping...
                    self._unacked_pids[PING_PID] = [asyncio.Event(), None]
                    await asyncio.wait_for(self._ping_n_wait(proto), self._c["response_time"])
                    dt = ticks_diff(ticks_ms(), proto.last_ack)
                sleep_time = rt_ms - dt
                if sleep_time < rt_ms / 4:  # avoid sending pings too frequently
                    sleep_time = rt_ms / 4
                await asyncio.sleep_ms(sleep_time)
        except Exception:
            await self._reconnect(proto, "keepalive")

    # _reconnect schedules a reconnection if not underway.
    # the proto passed in must be the one that caused the error in order to avoid closing a newly
    # connected proto when _reconnect gets called multiple times for one failure.
    async def _reconnect(self, proto, why, detail="n/a"):
        if self._state == 1 and self._proto == proto:
            log.info("dead socket: %s failed (%s)", why, detail)
            await self._proto.disconnect()  # should this be in a create_task() ?
            self._proto = None
            loop = asyncio.get_event_loop()
            if self._c["wifi_coro"] is not None:
                loop.create_task(self._c["wifi_coro"](False))  # Notify application

    # _keep_connected runs until disconnect() and ensures that there's always a connection.
    # It's strategy is to wait for the current connection to die and then to first reconnect at the
    # MQTT/TCP level. If that fails then it disconnects and reconnects wifi.
    # TODO:
    # - collect stats about which measures lead to success
    # - check whether first connection after wifi reconnect has to be delayed
    # - as an additional step, try to re-resolve dns
    async def _keep_connected(self):
        while self._state <= 1:
            if self._proto is not None:
                # We're connected, pause for 1 second
                await asyncio.sleep(_CONN_DELAY)
                continue
            # we have a problem, need some form of reconnection
            if self._c["interface"].isconnected():
                # wifi thinks it's connected, be optimistic and reconnect to broker
                try:
                    await self.connect()
                    log.debug("reconnect OK!")
                    continue
                except OSError as e:
                    # Can get ECONNABORTED or -1. The latter signifies no or bad CONNACK received.
                    # connecting to broker didn't work, disconnect Wifi
                    if (
                        self._proto is not None
                    ):  # defensive coding -- not sure this can be triggered
                        await self._reconnect(self._proto, "reconnect failed", e)
                self._c["interface"].disconnect()
                await asyncio.sleep(_CONN_DELAY)
                continue  # not falling through to force recheck of while condition
            # reconnect to Wifi
            try:
                await self.wifi_connect()
            except OSError as e:
                log.warning("error in Wifi reconnect: {}.".format(e))
                await asyncio.sleep(_CONN_DELAY)
        # log.debug('Disconnected, exited _keep_connected')
        self._conn_keeper = None

    async def subscribe(self, topic, qos=0):
        _qos_check(qos)
        pid = self._newpid()
        self._unacked_pids[pid] = [asyncio.Event(), None]
        while True:
            while self._proto is None:
                await asyncio.sleep(_CONN_DELAY)
            try:
                proto = self._proto
                await self._proto.subscribe(topic, qos, pid)
                actual_qos = await self._await_pid(pid)
                if actual_qos == qos:
                    return
                elif actual_qos == 0x80:
                    raise OSError(-2, "refused")
                else:
                    raise OSError(-2, "qos mismatch")
            except OSError as e:
                if e.args[0] == -2:
                    raise OSError(-1, "subscribe failed: " + e.args[1])
                await self._reconnect(proto, "sub", e)

    # publish with support for async. For QoS=0 this means publish and done. For QoS=1&sync=True
    # this means publish and wait for ack. For QoS=1&sync=False this means publish, then wait
    # for the _prev_pub slot to be available, e.g. by waiting for an ack.
    async def publish(self, topic, msg, retain=False, qos=0, sync=True):
        dup = 0
        pid = self._newpid() if qos else None
        message = MQTTMessage(topic, msg, retain, qos, pid)
        while True:
            # print("pub begin for pid=%s" % pid)
            # first we need a connection
            while self._proto is None:
                await asyncio.sleep(_CONN_DELAY)
            proto = self._proto
            try:
                # now publish the new packet on the same connection
                # print("pub->%s qos=%d pid=%s" % (message.topic, message.qos, message.pid))
                await proto.publish(message, dup)
                if qos == 0:
                    return
                # the following is atomic with the above publish
                self._unacked_pids[pid] = [asyncio.Event(), None]
                if not sync:
                    # async packet, need to wait 'til self._prev_pub becomes available
                    while self._prev_pub is not None:  # only False on the first async pub...
                        ppid = self._prev_pub.pid
                        if ppid is not None:
                            # print("pub pid=%d awaiting prev_pid=%d" % (pid, ppid))
                            await self._await_pid(ppid)
                        if self._prev_pub.pid == ppid:
                            # no-one has snatched the slot yet: our turn!
                            # print("pub pid=%d is now prev" % pid)
                            break
                    self._prev_pub = message
                    self._prev_pub_proto = proto
                else:
                    # sync packet
                    await self._await_pid(message.pid)
                return
            except OSError as e:
                await self._reconnect(proto, "pub", e)
