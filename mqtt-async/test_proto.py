# Test MQTTProto in mqtt_as.py
# This test runs under pytest on linux: pytest --cov=mqtt_as --cov-report=html
# It also runs in micropython: ./pyb test_proto.py

#try:
#    import pytest
#    pytestmark = pytest.mark.asyncio
#except:
#    pass

import sys
from mqtt_async import MQTTProto, MQTTMessage, MQTTConfig
import logging
logging.basicConfig(level=logging.DEBUG)

broker = ('192.168.0.14', 1883)
cli_id = 'mqtt_as_tester'
prefix = 'esp32/tests/'

try:
    import pytest
    pytestmark = pytest.mark.asyncio
except:
    pass

try:
    from time import ticks_ms, ticks_diff
except:
    from time import monotonic_ns
    def ticks_ms(): return monotonic_ns() // 1000000
    def ticks_diff(a, b): return a-b

try:
    import uasyncio as asyncio
    from uasyncio import sleep_ms
except:
    import asyncio
    async def sleep_ms(ms): await asyncio.sleep(ms/1000)

# callback handlers

pub_q = []
async def got_pub_coro(topic, msg, retain, qos):
    pub_q.append(MQTTMessage(topic, msg, retain, qos))
def got_pub(topic, msg, retain, qos):
    pub_q.append(MQTTMessage(topic, msg, retain, qos))

pingresp = False
def got_pingresp():
    global pingresp
    pingresp = True
puback_set = set()
def got_puback(pid):
    puback_set.add(pid)
suback_map = {}
def got_suback(pid, resp):
    suback_map[pid] = resp

def check_pingresp():
    global pingresp
    assert pingresp == True, "Error: got no ping response"
    pingresp = False

async def wait_msg(mqc, op):
    t0 = ticks_ms()
    while ticks_diff(ticks_ms(), t0) < 1000:
        if await mqc.read_msg() == op: return

# Quick simple connection
async def test_simple():
    global pub_q, puback_set, suback_map
    mqc = MQTTProto(got_pub, got_puback, got_suback, got_pingresp)
    # connect
    await mqc.connect(broker, cli_id, True)
    t0 = mqc.last_ack
    # try a ping
    await mqc.ping()
    await sleep_ms(10)
    await wait_msg(mqc, 0xd)
    assert mqc.last_ack != t0, "Error: did not receive ping response"
    check_pingresp()
    # subscribe at QoS=0
    topic = prefix + 'mirror'
    await mqc.subscribe(topic, 0, 123)
    await wait_msg(mqc, 9)
    assert 123 in suback_map, "Error: did not receive suback @qos=0"
    assert suback_map[123] == 0, "Error: subscribe rejected @qos=0"
    # publish to above topic using QoS=0
    await mqc.publish(MQTTMessage(topic, "hello"))
    await wait_msg(mqc, 3)
    assert len(pub_q) == 1, "Error: did not receive mirror pub @qos=0"
    assert pub_q[0].topic == topic.encode()
    assert pub_q[0].message == "hello".encode()
    assert pub_q[0].retain == 0
    assert pub_q[0].qos == 0
    pub_q = []
    # subscribe at QoS=1
    topic = prefix + 'mirror1'
    await mqc.subscribe(topic, 1, 124)
    await wait_msg(mqc, 9)
    assert 124 in suback_map
    assert suback_map[124] == 1, "Error: subscribe rejected @qos=1"
    # publish to above topic using QoS=1
    longm = "Hello this is a very very long message indeed, it's more than a couple bytes. "
    longm = longm + longm + longm + longm
    await mqc.publish(MQTTMessage(topic, longm, qos=1, pid=125))
    await wait_msg(mqc, 3)
    assert len(pub_q) == 1, "Error: did not receive mirror pub @qos=1"
    assert pub_q[0].topic == topic.encode()
    assert pub_q[0].message == longm.encode()
    assert pub_q[0].retain == 0
    assert pub_q[0].qos == 1
    assert 125 in puback_set, "Error: did not receive puback @qos=1"
    pub_q = []
    # publish to above topic using QoS=1 and a long message
    longm = bytearray(2000)
    for i in range(len(longm)):
        longm[i] = i & 0xff
    await mqc.publish(MQTTMessage(topic, longm, qos=1, pid=126))
    await wait_msg(mqc, 3)
    assert len(pub_q) == 1, "Error: did not receive mirror pub @qos=1"
    assert pub_q[0].topic == topic.encode()
    assert pub_q[0].message == longm
    assert pub_q[0].retain == 0
    assert pub_q[0].qos == 1
    assert 126 in puback_set, "Error: did not receive puback @qos=1"
    pub_q = []
    # disconnect
    await mqc.disconnect()
    #

async def test_coro_callback():
    global pub_q, puback_set, suback_map
    mqc = MQTTProto(got_pub_coro, got_puback, got_suback, got_pingresp)
    # connect
    await mqc.connect(broker, cli_id, True)
    # subscribe at QoS=0
    topic = prefix + 'mirror'
    await mqc.subscribe(topic, 0, 123)
    await wait_msg(mqc, 9)
    assert 123 in suback_map, "Error: did not receive suback @qos=0"
    assert suback_map[123] == 0, "Error: subscribe rejected @qos=0"
    # publish to above topic using QoS=0
    await mqc.publish(MQTTMessage(topic, "hello55"))
    await wait_msg(mqc, 3)
    assert len(pub_q) == 1, "Error: did not receive mirror pub @qos=0"
    assert pub_q[0].topic == topic.encode()
    assert pub_q[0].message == "hello55".encode()
    assert pub_q[0].retain == 0
    assert pub_q[0].qos == 0
    pub_q = []

async def test_close_write():
    return # ==========================================================================
    sr, sw = await asyncio.open_connection('192.168.0.14', 1883)
    print("connected")
    sw.close()
    await sw.wait_closed()
    print("closed")
    try:
    #with pytest.raises(ConnectionResetError):
        sw.write(b"hello")
        await sw.drain()
        assert True == False, "Error: drain on closed socket didn't raise"
    except OSError as e:
        print("Got OSError:", e)

async def test_read_closed():
    global pub_q, puback_set, suback_map
    mqc = MQTTProto(got_pub, got_puback, got_suback, got_pingresp)
    # connect
    await mqc.connect(broker, cli_id, True)
    # send garbage to cause the broker to close socket
    mqc._sock.write(b'\xf0\0')
    await mqc._sock.drain()
    # see whether we get a reasonable error
    try:
        r = await mqc._as_read(2)
        assert True == False, "Error: read on closed socket returned"
    except OSError as e:
        assert e.args[0] == -1
    #

async def test_write_closed():
    return # ==========================================================================
    global pub_q, puback_set, suback_map
    mqc = MQTTProto(got_pub, got_puback, got_suback, got_pingresp)
    # connect
    await mqc.connect(broker, cli_id, True)
    # explicitly close the socket
    mqc._sock.close()
    print("close called")
    await mqc._sock.wait_closed()
    print("wait_closed returned")
    # see whether we get a reasonable error
    try:
        w = await mqc._as_write(b'\xf0Hello')
        assert True == False, "Error: write on closed socket returned"
    except OSError as e:
        assert e.args[0] == 'Connection lost'
    #

async def test_open_fail():
    mqc = MQTTProto(got_pub, got_puback, got_suback, got_pingresp)
    # connect
    #with pytest.raises(OSError):
    print("Test bad port")
    try:
        await mqc.connect((broker[0], 33331), cli_id, True)
        assert True == False, "Error: write on closed socket returned"
    except OSError as e:
        print(e)
        assert e.args[0] == 111 # connection refused
    if False: # the following takes a while if enabled...
        print("Test bad host")
        try:
            await mqc.connect(('192.168.0.253', 33331), cli_id, True)
            assert True == False, "Error: write on closed socket returned"
        except OSError as e:
            print(e)
            assert e.args[0] == 113

async def test_last_will():
    global pub_q, puback_set, suback_map
    pub_q = []
    # construct last will object like MQTTClient would do
    conf = MQTTConfig()
    lw_topic = prefix + 'lw'
    conf.set_last_will(lw_topic, "bye")
    # connection 1 with last will
    conn1 = MQTTProto(got_pub, got_puback, got_suback, got_pingresp)
    await conn1.connect(broker, cli_id, True, keepalive=60, lw=conf.will)
    # connection 2 with subscription
    conn2 = MQTTProto(got_pub, got_puback, got_suback, got_pingresp)
    await conn2.connect(broker, cli_id+"-2", True)
    # subscribe to last will topic
    await conn2.subscribe(lw_topic, 0, 123)
    await wait_msg(conn2, 9)
    if not 123 in suback_map:
        print("Error: did not receive suback @qos=0")
    elif suback_map[123] != 0:
        print("Error: subscribe rejected @qos=0")
    # disconnect the socket - triggers a LW message in broker
    conn1._sock.close()
    await conn1._sock.wait_closed()
    await wait_msg(conn2, 3)
    assert len(pub_q) == 1
    assert pub_q[0].topic == lw_topic.encode()
    assert pub_q[0].message == "bye".encode()
    assert pub_q[0].retain == 0
    assert pub_q[0].qos == 0
    pub_q = []
    # disconnect
    await conn1.disconnect()
    await conn2.disconnect()

async def test_auth_fail():
    global pub_q, puback_set, suback_map
    mqc = MQTTProto(got_pub, got_puback, got_suback, got_pingresp)
    # connect no password
    exc = 0
    try:
        await mqc.connect(broker, cli_id, True, user="foo", pwd="")
    except OSError:
        exc += 1
    assert exc == 0 # FIXME FIXME need to fix broker auth to test this!
    assert mqc.last_ack != 0
    #
    await mqc.disconnect()

async def test_auth_succ():
    global pub_q, puback_set, suback_map
    mqc = MQTTProto(got_pub, got_puback, got_suback, got_pingresp)
    # connect with password
    await mqc.connect(broker, cli_id, True, user="foo", pwd="bar")
    assert mqc.last_ack != 0
    #
    await mqc.disconnect()

if sys.platform != 'linux':
    loop = asyncio.get_event_loop()
    test_funs = [ n for n in dir() if n.startswith("test_")]
    print("Running tests explicitly:", test_funs)
    good = 0
    bad  = 0
    #for test_fun in ['test_close_write']: #test_funs:
    for test_fun in test_funs:
        print("\n========= {} ==========".format(test_fun))
        try:
            loop.run_until_complete(eval(test_fun+'()'))
            good += 1
        except Exception as e:
            sys.print_exception(e)
            bad += 1
        print("==========")

    print("\n=================== {} passed, {} failed".format(good, bad))
