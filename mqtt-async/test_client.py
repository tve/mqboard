# Test MQTTClient in mqtt_async.py
# This test runs in cpython using pytest. It stubs/mocks MQTTProto so the test can focus exclusively
# on the client functionality, such as retransmissions.
# To produce code coverage with annotated html report: pytest --cov=mqtt_async --cov-report=html

import pytest, random, sys
pytestmark = pytest.mark.timeout(10)

import mqtt_async
from mqtt_async import MQTTClient, MQTTConfig, MQTTMessage

broker = ('192.168.0.14', 1883)
cli_id = 'mqtt_as_tester'
prefix = 'esp32/tests/'
RTT    = 40 # simulated broker response time in ms
mqtt_async._CONN_DELAY = RTT*2/1000 # set connection delay used by MQTTClient

# stuff that exists in MP but not CPython
from time import monotonic_ns
def ticks_ms(): return monotonic_ns() // 1000000
def ticks_diff(a, b): return a-b
import asyncio
async def sleep_ms(ms): await asyncio.sleep(ms/1000)

# -----Fake MQTTProto

FAIL_CLOSED = 1 # act as if socket had been closed or errored
FAIL_DROP   = 2 # act as if socket was functional but all packets get dropped
FAIL_SUB1   = 3 # fail subscription as if broker had refused (error code in suback)
FAIL_SUB2   = 4 # fail subscription as if broker had used the wrong qos

conn_fail  = 0  # number of consecutive connect() that should fail
conn_calls = 0  # number of times connect() got called, to verify reconnection timing

t0 = ticks_ms()

class FakeProto:

    def __init__(self, pub_cb, puback_cb, suback_cb, pingresp_cb, sock_cb=None):
        # Store init params
        self._pub_cb = pub_cb
        self._puback_cb = puback_cb
        self._suback_cb = suback_cb
        self._pingresp_cb = pingresp_cb
        self._sock_cb = sock_cb
        # Init private instance vars
        self._connected = False
        self._q = []      # queue of pending incoming messages (as function closures)
        # Init public instance vars
        self.last_ack = 0 # last ACK received from broker
        self.rtt = RTT    # milliseconds round-trip time for a broker response
        self.fail = None  # current failure mode
        print("Using FakeProto")

    async def connect(self, addr, client_id, clean, user=None, pwd=None, ssl_params=None,
            keepalive=0, lw=None):
        global conn_calls, conn_fail
        conn_calls += 1
        if conn_fail:
            await asyncio.sleep(4*RTT/1000) # simulate connection delay
            conn_fail -= 1
            raise OSError(-1, "simulated connection failure")
        await asyncio.sleep(2*RTT/1000) # simulate connection
        self._connected = True
        self._t0 = ticks_ms()
        self._last_pub = 0
        # simulate conn-connack round-trip
        self.last_ack = ticks_ms()
        print("Connected ack={}".format(self.last_ack))

    # _sleep_until calls sleep until the deadline is reached (approximately)
    async def _sleep_until(self, deadline):
        dt = ticks_diff(deadline, ticks_ms())
        if dt > 0: await asyncio.sleep_ms(dt)

    # _handle_ping_resp simulates receiving a ping response at time `when`
    async def _handle_ping_resp(self, when):
        await self._sleep_until(when)
        def f():
            self.last_ack = ticks_ms()
            self._pingresp_cb()
        self._q.append(f)

    async def ping(self):
        if self.fail == FAIL_CLOSED:
            raise OSError(1, "simulated closed")
        if self.fail != FAIL_DROP:
            asyncio.get_event_loop().create_task(self._handle_ping_resp(ticks_ms()+self.rtt))

    async def disconnect(self):
        await asyncio.sleep_ms(2) # let something else run to simulate write
        self._connected = False

    # _handle_puback simulates receiving a puback
    async def _handle_puback(self, when, pid):
        await self._sleep_until(when)
        def f():
            self.last_ack = ticks_ms()
            print("puback", pid)
            self._puback_cb(pid)
        self._q.append(f)

    # _handle_pub simulates receiving a pub message
    async def _handle_pub(self, when, msg):
        await self._sleep_until(when)
        def f(): self._pub_cb(msg)
        self._q.append(f)
        print("pub", len(self._q))

    async def publish(self, msg, dup=0):
        if self.fail == FAIL_CLOSED:
            raise OSError(1, "simulated closed")
        # space pubs out a tad else the replies can come out of order (oops!)
        now = ticks_ms()
        if ticks_diff(now, self._last_pub) < 10:
            await asyncio.sleep_ms(10)
            now = ticks_ms()
        self._last_pub = now
        # schedule publish effects unless we have a failure
        if self.fail != FAIL_DROP:
            loop = asyncio.get_event_loop()
            dt = 0
            if msg.qos > 0:
                loop.create_task(self._handle_puback(now+self.rtt, msg.pid))
                dt = 2*(msg.pid&1)
            print("Sched pid={} at {}".format(msg.pid, now+self.rtt+1-dt-t0))
            loop.create_task(self._handle_pub(now+self.rtt+1-dt, msg))
            await asyncio.sleep_ms(1) # ensure the above _handle_pubs start their wait now

    # _handle_suback simulates receiving a suback
    async def _handle_suback(self, when, pid, qos):
        await self._sleep_until(when)
        if   self.fail == FAIL_SUB1: qos = 0x80
        elif self.fail == FAIL_SUB2: qos = qos ^ 1
        def f():
            self.last_ack = ticks_ms()
            self._suback_cb(pid, qos)
        self._q.append(f)
        #print("suback now", len(self._q))

    async def subscribe(self, topic, qos, pid):
        if self.fail == FAIL_CLOSED:
            raise OSError(1, "simulated closed")
        if self.fail != FAIL_DROP:
            asyncio.get_event_loop().create_task(self._handle_suback(ticks_ms()+self.rtt, pid, qos))

    async def read_msg(self):
        while self._connected:
            if len(self._q) > 0:
                print("check_msg pop", len(self._q))
                self._q.pop(0)()
                return
            await asyncio.sleep_ms(10)
        raise OSError(-1, "Connection closed")

    def isconnected(self): return self._connected

# callbacks

msg_q = []
def subs_cb(msg):
    global msg_q
    print("got pub", msg.pid)
    msg_q.append(msg)

wifi_status = None
async def wifi_coro(status):
    print('wifi_coro({})'.format(status))
    global wifi_status
    wifi_status = status

conn_started = None
async def conn_start(cli):
    global conn_started
    conn_started = True

def reset_cb():
    global msg_q, wifi_status, conn_started
    msg_q = []
    wifi_status = None if sys.platform != 'linux' else True
    conn_started = None

cli_num = random.randrange(100000000) # add number to client id so each test
def fresh_config():
    global cli_num, conn_calls, conn_fail
    conn_calls = 0
    conn_fail = 0
    conf = MQTTConfig()
    conf.server = broker[0]
    conf.port = broker[1]
    conf.client_id = "{}-{}".format(cli_id, cli_num)
    cli_num += 1
    conf.wifi_coro = wifi_coro
    conf.subs_cb = subs_cb
    conf.connect_coro = conn_start
    conf.response_time = (3*RTT)/1000     # response time limit in fractional seconds
    conf.interface.disconnect()           # ensure all tests start disconnected
    return conf

async def connect_subscribe(topic, qos, clean=True, fake=True):
    conf = fresh_config()
    conf.debug = 3
    conf.clean = clean
    mqc = MQTTClient(conf)
    if fake:
        mqc._MQTTProto = FakeProto
    reset_cb()
    #
    await mqc.connect()
    assert wifi_status == True
    await asyncio.sleep_ms(10) # give created tasks a chance to run
    assert conn_started == True
    await mqc.subscribe(topic, qos)
    return (mqc, conf)

async def finish_test(mqc, conns=1):
    # initiate disconnect
    await mqc.disconnect()
    assert mqc._proto is None
    assert mqc._state == 2
    assert conn_calls == conns or conn_calls == 0 # zero if using real MQTTProto
    # wait a bit and ensure all tasks have finished
    await asyncio.sleep_ms(4*RTT)
    assert mqc._conn_keeper is None
    print(asyncio.all_tasks())
    assert len(asyncio.all_tasks()) == 1

#----- test cases using the real MQTTproto and connecting to a real broker

def test_instantiate():
    conf = fresh_config()
    mqc = MQTTClient(conf)
    mqc._MQTTProto = FakeProto
    assert mqc is not None

def test_dns_lookup():
    conf = fresh_config()
    mqc = MQTTClient(conf)
    mqc._MQTTProto = FakeProto
    mqc._dns_lookup()
    assert mqc._addr == broker

def test_mqtt_config():
    conf = MQTTConfig()
    #
    conf.foo = 'bar'
    assert conf.foo == 'bar'
    assert conf["foo"] == 'bar'
    #
    with pytest.raises(AttributeError):
        assert conf["bar"] == 'baz'
    conf["bar"] = 'baz'
    with pytest.raises(AttributeError):
        assert conf["bar"] == 'baz'
    conf.bar = 'baz'
    assert conf.bar == 'baz'
    assert conf["bar"] == 'baz'
    conf["bar"] = 'baz2'
    assert conf.bar == 'baz2'
    assert conf["bar"] == 'baz2'

def test_set_last_will():
    conf = MQTTConfig()
    exception = 0
    #
    try:
        conf.set_last_will("top", "mess", qos=2)
    except ValueError:
        exception += 1
    assert exception == 1
    #
    try:
        conf.set_last_will(None, "mess", qos=1)
    except ValueError:
        exception += 1
    assert exception == 2
    #
    conf.set_last_will("top", "mess", qos=1)
    assert conf.will.topic == b'top'
    assert conf.will.message == b'mess'
    assert conf.will.retain == False
    assert conf.will.qos == 1

def test_init_errors():
    conf = fresh_config()
    conf.will = "bye"
    with pytest.raises(ValueError, match=r'.*MQTTMessage.*'):
        mqc = MQTTClient(conf)
    #
    conf = fresh_config()
    conf.will = MQTTMessage("foo", "bar")
    conf.keepalive = 1000000
    with pytest.raises(ValueError, match='invalid keepalive'):
        mqc = MQTTClient(conf)
    #
    conf = fresh_config()
    conf.will = MQTTMessage("foo", "bar")
    conf.response_time = 10
    conf.keepalive = 10
    with pytest.raises(ValueError, match=r'keepalive.*time'):
        mqc = MQTTClient(conf)
    #
    conf = MQTTConfig()
    with pytest.raises(ValueError, match='no server'):
        mqc = MQTTClient(conf)
    #
    conf = fresh_config()
    conf.port = 0
    mqc = MQTTClient(conf)
    assert mqc._c.port == 1883
    #
    conf = fresh_config()
    conf.port = 0
    conf.ssl_params = 1
    mqc = MQTTClient(conf)
    assert mqc._c.port == 8883

@pytest.mark.asyncio
async def test_connect_disconnect():
    conf = fresh_config()
    conf.debug = 1
    mqc = MQTTClient(conf)
    mqc._MQTTProto = FakeProto
    assert mqc._state == 0
    assert mqc is not None
    await mqc.connect()
    assert mqc._proto is not None
    assert mqc._state == 1
    await asyncio.sleep_ms(5*RTT) # let new tasks settle
    await finish_test(mqc, conns=1)

# test a simple QoS 0 publication while everything works well
@pytest.mark.asyncio
async def test_pub_sub_qos0():
    mqc, conf = await connect_subscribe(prefix+"qos0", 0)
    #
    await mqc.publish(prefix+"qos0", "Hello0")
    await asyncio.sleep_ms(5*RTT)
    assert len(msg_q) == 1
    assert msg_q[0].message == b'Hello0'
    await finish_test(mqc)

# test a simple QoS 1 publication while everything works well
@pytest.mark.asyncio
async def test_pub_sub_qos1():
    mqc, conf = await connect_subscribe(prefix+"qos1", 1)
    #
    await mqc.publish(prefix+"qos1", "Hello1", qos=1)
    await asyncio.sleep_ms(5*RTT)
    assert len(msg_q) == 1
    assert msg_q[0].message == b'Hello1'
    await finish_test(mqc)

# test a subscription that the broker refuses
@pytest.mark.asyncio
async def test_refused_sub():
    mqc, conf = await connect_subscribe(prefix+"qos1", 1)
    #
    mqc._proto.fail = FAIL_SUB1
    with pytest.raises(OSError):
        await mqc.subscribe(prefix+"ref1", 0)
    #
    mqc._proto.fail = FAIL_SUB2
    with pytest.raises(OSError):
        await mqc.subscribe(prefix+"ref1", 0)
    #
    await finish_test(mqc)

# test a QoS 1 publication while the socket drops everything, it should reconnect
@pytest.mark.asyncio
async def test_drop_qos1():
    mqc, conf = await connect_subscribe(prefix+"qos1d", 0)
    #
    proto1 = mqc._proto
    proto1.fail = FAIL_DROP
    await mqc.publish(prefix+"qos1d", "Hello2", qos=1)
    await asyncio.sleep_ms(5*RTT)
    assert len(msg_q) >= 1
    assert msg_q[0].message == b'Hello2'
    assert mqc._proto != proto1 # we have reconnected in the process
    #
    await finish_test(mqc, conns=2)

# test a QoS 1 publication while the socket fails everything, it should reconnect
@pytest.mark.asyncio
async def test_fail_qos1():
    mqc, conf = await connect_subscribe(prefix+"qos1f", 0)
    #
    proto1 = mqc._proto
    proto1.fail = FAIL_CLOSED
    await mqc.publish(prefix+"qos1f", "Hello3", qos=1)
    await asyncio.sleep_ms(5*RTT)
    assert len(msg_q) >= 1
    assert msg_q[0].message == b'Hello3'
    assert mqc._proto != proto1 # we have reconnected in the process
    #
    await finish_test(mqc, conns=2)

# test a QoS 1 subscription while the socket drops everything, it should reconnect
@pytest.mark.asyncio
async def test_drop_sub1():
    mqc, conf = await connect_subscribe(prefix+"sub1x", 0)
    #
    proto1 = mqc._proto
    proto1.fail = FAIL_DROP
    await mqc.subscribe(prefix+"sub1d", 1)
    await mqc.publish(prefix+"sub1d", "Hello4", qos=1)
    await asyncio.sleep_ms(5*RTT)
    assert len(msg_q) >= 1
    assert msg_q[0].message == b'Hello4'
    assert mqc._proto != proto1 # we have reconnected in the process
    #
    await finish_test(mqc, conns=2)

# test a QoS 1 subscription while the socket fails everything, it should reconnect
@pytest.mark.asyncio
async def test_fail_sub1():
    mqc, conf = await connect_subscribe(prefix+"sub1x", 0)
    #
    proto1 = mqc._proto
    proto1.fail = FAIL_DROP
    await mqc.subscribe(prefix+"sub1f", 1)
    await mqc.publish(prefix+"sub1f", "Hello5", qos=1)
    await asyncio.sleep_ms(5*RTT)
    assert len(msg_q) >= 1
    assert msg_q[0].message == b'Hello5'
    assert mqc._proto != proto1 # we have reconnected in the process
    #
    await finish_test(mqc, conns=2)

# test reconnect failing multiple times
@pytest.mark.asyncio
async def test_fail_reconnect():
    mqc, conf = await connect_subscribe(prefix+"sub1x", 0)
    #
    global conn_fail
    conn_fail = 2
    mqc._proto.fail = FAIL_CLOSED
    await asyncio.sleep_ms(20*RTT)
    await finish_test(mqc, conns=4)

# The following tests can also be run against a real broker. For this set FAKE=False and
# run `pytest with -k async_`
FAKE=True

# test async pub
@pytest.mark.asyncio
async def test_async_pub_simple():
    topic = prefix+"async1"
    mqc, conf = await connect_subscribe(topic, 1, clean=False, fake=FAKE)
    #
    assert len(mqc._unacked_pids) == 0
    await mqc.publish(topic, "Hello1", qos=1, sync=False)
    assert len(mqc._unacked_pids) <= 1
    await mqc.publish(topic, "Hello2", qos=1, sync=False)
    assert len(mqc._unacked_pids) <= 1
    await mqc.publish(topic, "Hello3", qos=1, sync=True)
    assert len(mqc._unacked_pids) == 0
    await asyncio.sleep_ms(5*RTT)
    assert len(msg_q) == 3
    assert msg_q[0].message == b'Hello1'
    assert msg_q[1].message == b'Hello2'
    assert msg_q[2].message == b'Hello3'
    await finish_test(mqc)

# test async pub ordering
@pytest.mark.asyncio
async def test_async_pub_ordering():
    topic = prefix+"async2"
    mqc, conf = await connect_subscribe(topic, 1, clean=False, fake=FAKE)
    #
    num = 20
    t0 = ticks_ms()
    for i in range(num):
        print("*** pub {} at {}s***".format(i, ticks_diff(ticks_ms(), t0)//1000))
        m = "Hello {}".format(i)
        if not FAKE and i%3 == 2:
                mqc._proto._sock.send(b'\0\0')
                print("FAIL_ABORT")
        await mqc.publish(topic, m, qos=1, sync=False)
        if FAKE and i%3 == 2:
            mqc._proto.fail = FAIL_CLOSED
            print("FAIL_CLOSED")
        assert len(mqc._unacked_pids) <= 1
    #
    await asyncio.sleep_ms(5*RTT)
    assert len(msg_q) >= num
    for i in range(len(msg_q)):
        print("{}: {}".format(i, msg_q[i].message))
    i = 0
    while i < len(msg_q):
        # remove duplicates
        while i > 0 and msg_q[i].message == msg_q[i-1].message:
            del msg_q[i]
        print("{}: {}".format(i, msg_q[i].message))
        m = "Hello {}".format(i)
        assert msg_q[i].message == m.encode()
        i += 1
    #
    await finish_test(mqc, conns=num//3+1)

