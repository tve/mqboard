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

VERSION = (0, 7, 4)

import gc, socket, struct
from binascii import hexlify
from errno import EINPROGRESS
from sys import platform

try:
    # imports used with Micropython
    from micropython import const
    from time import ticks_ms, ticks_diff
    import uasyncio as asyncio
    async def open_connection(addr):
        return ( await asyncio.open_connection(addr[0], addr[1]) )[0]
    gc.collect()
    from machine import unique_id
    gc.collect()
    import network
    STA_IF = network.WLAN(network.STA_IF)
    gc.collect()
    def is_awaitable(f): return f.__class__.__name__ == 'generator'
except:
    # Imports used with CPython (moved to another file so they don't appear on MP HW)
    from cpy_fix import *

try:
    import logging
    log = logging.getLogger(__name__)
except:
    class Logger: # please upip.install('logging')
        def debug(self, msg, *args): pass
        def info(self, msg, *args): print(msg % (args or ()))
        def warning(self, msg, *args): print(msg % (args or ()))
    log = Logger()

# Timing parameters and constants

# Response time of the broker to requests, such as pings, before MQTTClient deems the connection
# to be broken and tries to reconnect. MQTTClient issues an explicit ping if there is no outstanding
# request to the broker for half the response time. This means that if the connection breaks and
# there is no outstanding request it could take up to 1.5x the response time until MQTTClient
# notices.
# Specified in MQTTConfig.response_time, suggested to be in the range of 60s to a few minutes.

# Connection time-out when establishing an MQTT connection to the broker:
# Specified in MQTTConfig.conn_timeout in seconds

# Keepalive interval with broker per MQTT spec. Determines at what point the broker sends the last
# will message. Pretty much irrelevant if no last-will message is set. This interval must be greater
# than 2x the response time.
# Specified in MQTTConfig.keepalive

# Default long delay in seconds when waiting for a connection to be re-established.
# Can be overridden in tests to make things go faster
_CONN_DELAY = const(1)

# Error strings used with OSError(-1, ...) for internally raised errors.
CONN_CLOSED = "Connection closed"
CONN_TIMEOUT = "Connection timed out"
PROTO_ERROR = "Protocol error"

# MQTTConfig is a "dumb" struct-like class that holds config info for MQTTClient and MQTTProto.
class MQTTConfig:
    # __init__ sets default values
    def __init__(self):
        self.client_id       = hexlify(unique_id())
        self.server          = None
        self.port            = 0
        self.user            = None
        self.password        = b''
        self.response_time   = 10  # in seconds
        self.keepalive       = 600 # in seconds, only sent if self.will != None
        self.ssl_params      = None
        self.interface       = STA_IF
        self.clean           = True
        self.will            = None             # last will message, must be MQTTMessage
        self.subs_cb          = lambda *_: None  # callback when message arrives for a subscription
        self.wifi_coro       = None             # notification when wifi connects/disconnects
        self.connect_coro    = None             # notification when a MQTT connection starts
        self.ssid            = None
        self.wifi_pw         = None
        # The following are not currently supported:
        #self.sock_cb         = None             # callback for esp32 socket to allow bg operation
        #self.listen_interval = 0                # Wifi listen interval for power save
        #self.conn_timeout    = 120 # in seconds

    # support map-like access for backwards compatibility
    def __getitem__(self, key):
        return getattr(self, key)
    # support map-like access for backwards compatibility
    def __setitem__(self, key, value):
        if not hasattr(self, key):
            log.warning("MQTTConfig.%s ignored", key)
        else:
            setattr(self, key, value)

    # set_last_will records the last will, it is actually transmitted to the broker on connect
    def set_last_will(self, topic, message, retain=False, qos=0):
        qos_check(qos)
        if not topic:
            raise ValueError('empty topic')
        self.will = MQTTMessage(topic, message, retain, qos)

config = MQTTConfig()

def qos_check(qos):
    if not (qos == 0 or qos == 1):
        raise ValueError('unsupported qos')

class MQTTMessage:
    def __init__(self, topic, message, retain=False, qos=0, pid=None):
        #if qos and pid is None:
        #    raise ValueError('pid missing')
        qos_check(qos)
        if isinstance(topic, str): topic = topic.encode()
        if isinstance(message, str): message = message.encode()
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
        self.last_ack = 0 # last ACK received from broker

    # connect initiates a connection to the broker at addr.
    # Addr should be the result of a gethostbyname (typ. an ip-address and port tuple).
    # The clean parameter corresponds to the MQTT clean connection attribute.
    # Connect waits for the connection to get established and for the broker to ACK the connect packet.
    # It raises an OSError if the connection cannot be made.
    # Reusing an MQTTProto for a second connection is not recommended.
    async def connect(self, addr, client_id, clean, user=None, pwd=None, ssl_params=None,
            keepalive=0, lw=None):
        if lw is None:
            keepalive = 0
        log.info('Connecting to %s id=%s clean=%d', addr, client_id, clean)
        try:
            # in principle, open_connection returns a (reader,writer) stream tuple, but in MP it
            # really returns a bidirectional stream twice, so we cheat and use only one of the tuple
            # values for everything.
            self._sock = await open_connection(addr)
        except OSError as e:
            if e.args[0] != EINPROGRESS:
                raise
        await asyncio.sleep_ms(10) # sure sure this is needed...
        #if self._sock_cb is not None: # st socket event for mqrepl's use
        #    self._sock.setsockopt(socket.SOL_SOCKET, 20, self._sock_cb)
        assert ssl_params is None, "TLS not yet supported" # :-(
        #if ssl_params is not None:
        #    log.debug("Wrapping SSL")
        #    import ssl
        #    self._sock = ssl.wrap_socket(self._sock, **ssl_params)
        # Construct connect packet
        premsg = bytearray(b"\x10\0\0\0\0")   # Connect message header
        msg = bytearray(b"\0\x04MQTT\x04\0\0\0")  # Protocol 3.1.1
        if isinstance(client_id, str):
            client_id = client_id.encode()
        sz = 10 + 2 + len(client_id)
        msg[7] = (clean&1) << 1
        if user is not None:
            if isinstance(user, str): user = user.encode()
            if isinstance(pwd, str): pwd = pwd.encode()
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
        if self._sock is None: await asyncio.sleep_ms(100) # esp32 glitch
        await self._as_write(premsg[:i], drain=False)
        await self._as_write(msg, drain=False)
        await self._send_str(client_id, drain=False)
        if lw is not None:
            await self._send_str(lw.topic) # let it drain in case message is long
            await self._send_str(lw.message)
        if user is not None:
            await self._send_str(user, drain=False)
            await self._send_str(pwd, drain=False)
        await self._as_write(b'') # cause drain
        # Await CONNACK
        # read causes ECONNABORTED if broker is out
        resp = await self._as_read(4)
        if resp[3] != 0 or resp[0] != 0x20 or resp[1] != 0x02:
            raise OSError(-1)  # Bad CONNACK e.g. authentication fail.
        self.last_ack = ticks_ms()
        log.debug('Connected')  # Got CONNACK

    # ===== Helpers

    # _as_read reads n bytes from the socket in a blocking manner using asyncio and returns them as
    # bytes. On error *and on EOF* it raises an OSError.
    # There is no time-out, instead, as_read relies on the socket being closed by a watchdog.
    # _as_read buffers a bunch of bytes because calling self.sock._read takes 4-5ms minumum and
    # _read_msg does a good number of very short reads.
    async def _as_read(self, n):
        # Note: uasyncio.Stream.read returns short reads
        #t0 = ticks_ms()
        while self._sock:
            # read missing amt
            missing = n - len(self._read_buf)
            if missing > 0:
                if missing < 128:
                    missing = 128
                got = await self._sock.read(missing)
                if len(got) == 0:
                    raise OSError(-1, CONN_CLOSED)
                self._read_buf += got
                missing = n - len(self._read_buf)
            # got enough?
            if missing <= 0:
                res = self._read_buf[:n]
                self._read_buf = self._read_buf[n:]
                #print("rd", len(res), "in", ticks_diff(ticks_ms(), t0))
                return res
        raise OSError(-1, CONN_CLOSED)
    _read_buf = b''

    # _as_write writes n bytes to the socket in a blocking manner using asyncio. On error or EOF
    # it raises an OSError.
    # There is no time-out, instead, as_write relies on the socket being closed by a watchdog.
    async def _as_write(self, bytes_wr, drain=True):
        if self._sock is None:
            raise OSError(-1, CONN_CLOSED)
        if bytes_wr != b'':
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
            n |= (b & 0x7f) << sh
            if not b & 0x80:
                return n
            sh += 7

    # _write_varint writes 'value' into 'array' starting at offset 'index'. It returns the index
    # after the last byte placed into the array. Only positive values are handled.
    def _write_varint(self, array, index, value):
        while value > 0x7f:
            array[index] = (value & 0x7f) | 0x80
            value >>= 7
            index += 1
        array[index] = value
        return index+1

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
                await asyncio.wait_for(self._sock.drain(), 0.2) # 200ms to make sure ipoll gets a chance
        except:
            pass
        if self._sock is not None:
            self._sock.close()
            await self._sock.wait_closed()
        self._sock = None

    def isconnected(self): self._sock is not None

    # publish writes a publish message onto the current socket. It raises an OSError on failure.
    # If qos==1 then a pid must be provided.
    # msg.topic and msg.message must be byte arrays, or equiv.
    async def publish(self, msg, dup=0):
        # calculate message length
        mlen = len(msg.message)
        sz = 2 + len(msg.topic) + mlen
        if msg.qos > 0:
            sz += 2 # account for pid
        if sz >= 2097152:
            raise ValueError('message too long')
        # construct packet: if possible, put everything into a single large bytearray so a single
        # socket send call can be made resulting in a single packet.
        hdrlen = 4+2+len(msg.topic)+2
        single = hdrlen + mlen <= 1440 # slightly conservative MSS
        if single:
            pkt = bytearray(hdrlen+mlen)
        else:
            pkt = bytearray(hdrlen)
        pkt[0] = 0x30 | msg.qos << 1 | msg.retain | dup << 3
        l = self._write_varint(pkt, 1, sz)
        struct.pack_into("!H", pkt, l, len(msg.topic))
        l += 2
        pkt[l:l+len(msg.topic)] = msg.topic
        l += len(msg.topic)
        if msg.qos > 0:
            struct.pack_into("!H", pkt, l, msg.pid)
            l += 2
        # send header and body
        async with self._lock:
            if single:
                pkt[l:] = msg.message
                await self._as_write(pkt)
            else:
                await self._as_write(pkt[:l])
                await self._as_write(msg.message)

    # subscribe sends a subscription message.
    async def subscribe(self, topic, qos, pid):
        if (qos & 1) != qos:
            raise ValueError("invalid qos")
        pkt = bytearray(b"\x82\0\0\0")
        if isinstance(topic, str): topic = topic.encode()
        struct.pack_into("!BH", pkt, 1, 2 + 2 + len(topic) + 1, pid)
        async with self._lock:
            await self._as_write(pkt, drain=False)
            await self._send_str(topic, drain=False)
            await self._as_write(qos.to_bytes(1, "little"))

    # Read a single MQTT message and process it.
    # Subscribed messages are delivered to a callback previously set by .setup() method.
    # Other (internal) MQTT messages processed internally.
    # Called from ._handle_msg().
    async def read_msg(self):
        #t0 = ticks_ms()
        res = await self._as_read(1)
        # We got something, dispatch based on message type
        op = res[0]
        if op == 0xd0:  # PINGRESP
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
            #print("suback", resp[3])
            self.last_ack = ticks_ms()
            self._suback_cb(pid, resp[3])
        elif (op & 0xf0) == 0x30:  # PUB: dispatch to user handler
            sz = await self._read_varint()
            topic_len = await self._as_read(2)
            topic_len = (topic_len[0] << 8) | topic_len[1]
            topic = await self._as_read(topic_len)
            sz -= topic_len + 2
            retained = op & 0x01
            qos = (op>>1) & 3
            pid = None
            if qos: # not QoS=0 -> got pid
                pid = await self._as_read(2)
                pid = pid[0] << 8 | pid[1]
                sz -= 2
            if sz < 0:
                raise OSError(-1, PROTO_ERROR, "pub sz", sz)
            else:
                msg = await self._as_read(sz)
            # Dispatch to user's callback handler
            log.debug("dispatch pub %s pid=%s qos=%d", topic, pid, qos)
            #t1 = ticks_ms()
            cb = self._subs_cb(topic, msg, bool(retained), qos)
            if is_awaitable(cb):
                await cb # handle _subs_cb being coro
            #t2 = ticks_ms()
            # Send PUBACK for QoS 1 messages
            if qos == 1:
                pkt = bytearray(b"\x40\x02\0\0")
                struct.pack_into("!H", pkt, 2, pid)
                async with self._lock:
                    await self._as_write(pkt)
            elif qos == 2:
                raise OSError(-1, "QoS=2 not supported")
            #log.debug("read_msg: read:{} handle:{} ack:{}".format(ticks_diff(t1, t0),
            #    ticks_diff(t2, t1), ticks_diff(ticks_ms(), t2)))
        else:
            raise OSError(-1, PROTO_ERROR, "bad op", op)
        return op>>4

#-----------------------------------------------------------------------------------------

PING_PID = const(100000) # fake pid used in handling of ping acks

# MQTTClient class.
class MQTTClient():

    def __init__(self, config):
        # handle config
        self._c = config
        # config last will and keepalive
        if self._c.will is None:
            self._c.keepalive = 0 # no point setting MQTT keepalive if there's no lw
        elif not isinstance(self._c.will, MQTTMessage):
            raise ValueError('will must be MQTTMessage')
        if self._c.keepalive >= 65536:
            raise ValueError('invalid keepalive')
        if self._c.keepalive > 0 and self._c.keepalive < self._c.response_time * 2:
            raise ValueError("keepalive <2x response_time")
        # config server and port
        if config.port == 0:
            self._c.port = 8883 if config.ssl_params else 1883
        if config.server is None:
            raise ValueError('no server')
        # init instance vars
        self._proto = None
        self._MQTTProto = MQTTProto # reference to class, override for testing
        self._addr = None
        self._lastpid = 0
        self._unacked_pids = {}     # PUBACK and SUBACK pids awaiting ACK response
        self._state = 0             # 0=init, 1=has-connected, 2=disconnected=dead
        self._conn_keeper = None    # handle to persistent keep-connection coro
        self._prev_pub = None       # MQTTMessage of as yet unacked async pub
        self._prev_pub_proto = None # self._proto used for as yet unacked async pub
        # misc
        if platform == "esp8266":
            import esp
            esp.sleep_type(0)  # Improve connection integrity at cost of power consumption.

    async def wifi_connect(self):
        log.info("connecting wifi")
        s = self._c.interface
        if platform == 'esp8266':
            if s.isconnected():  # 1st attempt, already connected.
                return
            s.active(True)
            s.connect()  # ESP8266 remembers connection.
            for _ in range(60):
                if s.status() != network.STAT_CONNECTING:  # Break out on fail or success. Check once per sec.
                    break
                await asyncio.sleep(_CONN_DELAY)
            if s.status() == network.STAT_CONNECTING:  # might hang forever awaiting dhcp lease renewal or something else
                s.disconnect()
                await asyncio.sleep(_CONN_DELAY)
            if not s.isconnected() and self._c.ssid is not None and self._c.wifi_pw is not None:
                s.connect(self._c.ssid, self._c.wifi_pw)
                while s.status() == network.STAT_CONNECTING:  # Break out on fail or success. Check once per sec.
                    await asyncio.sleep(_CONN_DELAY)
        elif self._c.ssid:
            s.active(True)
            #log.debug("Connecting, li=%d", self._c.listen_interval)
            s.connect(self._c.ssid, self._c.wifi_pw)
            #s.connect(self._c.ssid, self._c.wifi_pw, listen_interval=self._c.listen_interval)
#            if PYBOARD:  # Doesn't yet have STAT_CONNECTING constant
#                while s.status() in (1, 2):
#                    await asyncio.sleep(_CONN_DELAY)
#            else:
            while s.status() == network.STAT_CONNECTING:  # Break out on fail or success.
                await asyncio.sleep_ms(200)
        else:
            raise OSError(-1, "no SSID to connect to Wifi")

        if not s.isconnected():
            log.warning("Wifi failed to connect")
            raise OSError(-1, "Wifi failed to connect")

    def _dns_lookup(self):
        new_addr = socket.getaddrinfo(self._c.server, self._c.port)
        if len(new_addr) > 0 and len(new_addr[0]) > 1:
            self._addr = new_addr[0][-1]
        log.debug("DNS %s->%s", self._c.server, self._addr)

    async def connect(self):
        if self._state > 1:
            raise ValueError("cannot reuse")
        clean = False
        # deal with wifi and dns
        if not self._c.interface.isconnected():
            await self.wifi_connect()
        if self._state == 0:
            self._dns_lookup() # DNS is blocking, do it only the first time around
            clean = self._c.clean
        # actually open a socket and connect
        proto = self._MQTTProto(self._c.subs_cb, self._got_puback, self._got_suback,
                self._got_pingresp)
        # FIXME: need to use a timeout here!
        await proto.connect(self._addr, self._c.client_id, clean,
                user=self._c.user, pwd=self._c.password, ssl_params=self._c.ssl_params,
                keepalive=self._c.keepalive,
                lw=self._c.will) # raises on error
        self._proto = proto
        # update state
        if self._state == 0:
            self._state = 1
            # this is the first time we connect, if we asked for a clean session we need to
            # disconnect and reconnect with clean=False so the broker doesn't drop all the state
            # when we get our first disconnect due to network issues
            if clean:
                await self._proto.disconnect()
                self._proto = None
                return await self.connect()
        elif self._state > 1:
            await self.disconnect() # whoops, someone called disconnect() while we were connecting
            raise OSError(-1, "disconnect while connecting")
        # If we get here without error broker/LAN must be up.
        loop = asyncio.get_event_loop()
        # Notify app that Wifi is up
        if self._c.wifi_coro is not None:
            loop.create_task(self._c.wifi_coro(True))  # Notify app that Wifi is up
        # Start background coroutines that run until the user calls disconnect
        if self._conn_keeper is None:
            self._conn_keeper = loop.create_task(self._keep_connected())
        # Start background coroutines that quit on connection fail
        loop.create_task(self._handle_msgs(self._proto))
        loop.create_task(self._keep_alive(self._proto))
        # Notify app that we're connceted and ready to roll
        if self._c.connect_coro is not None:
            loop.create_task(self._c.connect_coro(self))
        #log.debug("connected")

    async def disconnect(self):
        self._state = 2 # dead - do not reconnect
        if self._proto is not None:
            await self._proto.disconnect() # should we do a create_task here?
        self._proto = None

    #===== Manage PIDs and ACKs
    # self._unacked_pids is a hash that contains unacked pids. Each hash value is a list, the first
    # element of which is an asycio.Event that gets set when an ack comes in. The second element is
    # the return qos value in the case of a subscribe and is None in the case of a publish.

    def _newpid(self):
        self._lastpid += 1
        if self._lastpid > 65535: self._lastpid = 1
        return self._lastpid

    # _got_puback handles a puback by removing the pid from those we're waiting for
    def _got_puback(self, pid):
        if pid in self._unacked_pids:
            self._unacked_pids[pid][0].set()

    def _got_pingresp(self): self._got_puback(PING_PID)

    # _got_suback handles a suback by checking that the desired qos level was acked and
    # either removing the pid from the unacked set or flagging it with an OSError.
    def _got_suback(self, pid, actual_qos):
        if pid in self._unacked_pids:
            self._unacked_pids[pid][1] = actual_qos
            self._unacked_pids[pid][0].set()

    # _await_pid waits until the broker ACKs a pub or sub message, or it times out.
    # It returns the second element of the self._unacked_pids list (may be None).
    async def _await_pid(self, pid):
        if pid not in self._unacked_pids:
            return None
        # wait for ACK to come in with a timeout # TODO: calculate timeout based on time sent
        try:
            if not self._unacked_pids[pid][0].is_set():
                await asyncio.wait_for(self._unacked_pids[pid][0].wait(), self._c.response_time)
        except asyncio.TimeoutError:
            raise OSError(-1, CONN_TIMEOUT)
        # return second list element
        ret = self._unacked_pids[pid][1]
        del self._unacked_pids[pid]
        return ret

    #===== Background coroutines

    # Launched by connect. Runs until connectivity fails. Checks for and
    # handles incoming messages.
    async def _handle_msgs(self, proto):
        try:
            while True:
                await proto.read_msg()
        except OSError as e:
            await self._reconnect(proto, 'read_msg', e)

    # ping and wait for response, wrapped in a coroutine to be used in asyncio.wait_for()
    async def _ping_n_wait(self, proto):
        await proto.ping()
        await self._await_pid(PING_PID)

    # Keep connection alive MQTT spec 3.1.2.10 Keep Alive.
    # Runs until ping failure or no response in keepalive period.
    async def _keep_alive(self, proto):
        rt_ms = self._c.response_time*1000
        try:
            while proto.isconnected():
                dt = ticks_diff(ticks_ms(), proto.last_ack)
                if dt > rt_ms:
                    # it's time for another ping...
                    self._unacked_pids[PING_PID] = [ asyncio.Event(), None ]
                    await asyncio.wait_for(self._ping_n_wait(proto), self._c.response_time)
                    dt = ticks_diff(ticks_ms(), proto.last_ack)
                sleep_time = rt_ms - dt
                if sleep_time < rt_ms/4: # avoid sending pings too frequently
                    sleep_time = rt_ms/4
                await asyncio.sleep_ms(sleep_time)
        except Exception as e:
            await self._reconnect(proto, 'keepalive')

    # _reconnect schedules a reconnection if not underway.
    # the proto passed in must be the one that caused the error in order to avoid closing a newly
    # connected proto when _reconnect gets called multiple times for one failure.
    async def _reconnect(self, proto, why, detail="n/a"):
        if self._state == 1 and self._proto == proto:
            log.debug("dead socket: %s failed (%s)", why, detail)
            await self._proto.disconnect() # should this be in a create_task() ?
            self._proto = None
            loop = asyncio.get_event_loop()
            if self._c.wifi_coro is not None:
                loop.create_task(self._c.wifi_coro(False))  # Notify application

    # _keep_connected runs until disconnect() and ensures that there's always a connection.
    # It's strategy is to wait for the current connection to die and then to first reconnect at the
    # MQTT/TCP level. If that fails then it disconnects and reconnects wifi.
    # TODO:
    # - collect stats about which measures lead to success
    # - check whether first connection after wifi reconnect has to be delayed
    # - as an additional step, try to re-resolve dns
    async def _keep_connected(self):
        while self._state == 1:
            if self._proto is not None:
                # We're connected, pause for 1 second
                await asyncio.sleep(_CONN_DELAY)
                continue
            # we have a problem, need some form of reconnection
            if self._c.interface.isconnected():
                # wifi thinks it's connected, be optimistic and reconnect to broker
                try:
                    await self.connect()
                    log.debug('reconnect OK!')
                    continue
                except OSError as e:
                    log.warning('error in MQTT reconnect.', e)
                    # Can get ECONNABORTED or -1. The latter signifies no or bad CONNACK received.
                # connecting to broker didn't work, disconnect Wifi
                if self._proto is not None: # defensive coding -- not sure this can be triggered
                    await self._reconnect(self._proto, "reconnect failed")
                self._c.interface.disconnect()
                await asyncio.sleep(_CONN_DELAY)
                continue # not falling through to force recheck of while condition
            # reconnect to Wifi
            try:
                await self.wifi_connect()
            except OSError as e:
                log.warning('error in Wifi reconnect.', e)
                await asyncio.sleep(_CONN_DELAY)
        #log.debug('Disconnected, exited _keep_connected')
        self._conn_keeper = None

    async def subscribe(self, topic, qos=0):
        qos_check(qos)
        pid = self._newpid()
        self._unacked_pids[pid] = [ asyncio.Event(), None ]
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
            await self._reconnect(proto, 'sub')

    # publish with support for async, meaning that the packet is published but an ack (if qos 1) is
    # not awaited. Instead the ack is awaited after the next packet is published.
    # Algorithm:
    # 1. If prev packet was async:
    #   a. if got ACK go to step 2
    #   b. if still on same socket, go to step 2
    #   c. (no ACK and new socket) retransmit prev packet
    # 2. Transmit new packet
    # 3. If prev packet was async:
    #   a. wait for ACK with timeout, if got ACK go to step 4
    #   b. reconnect, retransmit prev packet, go to step 2
    # 3. If new packet is QoS=0 or async, return success
    # 4. (new packet is QoS=1 and sync) wait for ACK
    async def publish(self, topic, msg, retain=False, qos=0, sync=True):
        dup = 0
        pid = self._newpid() if qos else None
        message = MQTTMessage(topic, msg, retain, qos, pid)
        if qos:
            self._unacked_pids[pid] = [ asyncio.Event(), None ]
        while True:
            log.debug("pub begin for pid=%s", pid)
            # first we need a connection
            while self._proto is None:
                await asyncio.sleep(_CONN_DELAY)
            # if there is an async packet outstanding and it has not been acked, and a new connection
            # has been established then begin by retransmitting that packet.
            proto = self._proto
            if self._prev_pub is not None and pid in self._unacked_pids and \
                    self._prev_pub_proto != proto:
                m = self._prev_pub
                log.warning("repub->%s qos=%d pid=%d", m.topic, m.qos, m.pid)
                self._prev_pub_proto = proto
                try:
                    await proto.publish(m, dup=1)
                except OSError as e:
                    await self._reconnect(proto, 'pub')
                    continue
            # now publish the new packet on the same connection
            log.debug("pub->%s qos=%d pid=%d", message.topic, message.qos, message.pid)
            try:
                await proto.publish(message, dup)
            except OSError as e:
                await self._reconnect(proto, 'pub')
                continue
            # if there is an async packet outstanding wait for an ack
            if self._prev_pub is not None:
                try:
                    await self._await_pid(self._prev_pub.pid)
                except OSError as e:
                    await self._reconnect(proto, 'pub')
                    continue
                self._prev_pub = None
                self._prev_pub_proto = None
            # new packet one becomes prev if qos>0 and async, or gotta wait for new one's ack if sync
            if qos == 0:
                return
            if not sync:
                self._prev_pub = message
                self._prev_pub_proto = proto
                return
            try:
                await self._await_pid(message.pid)
                return
            except OSError as e:
                await self._reconnect(proto, 'pub')
