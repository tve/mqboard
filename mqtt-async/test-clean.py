# Test clean flag with MQTTProto in mqtt_as.py
# Running this test requires a broker and a topic that the test can subscribe to and publish to.
# This test runs under micropython (`./pyb test-clean.py`)
# Failures are not obvious, one has to interpret the output (sorry, this is used more to ensure
# correct understanding of the MQTT/broker behavior than as a unit test).

from mqtt_as import MQTTProto, MQTTMessage

broker = ('192.168.0.14', 1883)  # change to your broker's IP address or hostname
cli_id = 'mqtt_as_tester'        # change if you need to use a specific MQTT client id
prefix = 'esp32/tests/'          # prefix for the (couple of) test topics used

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
    def sleep_ms(ms): asyncio.sleep(ms/1000)

# callback handlers

pid = 100
pub_q = []
def got_pub(msg):
    pub_q.append(msg)

puback_set = set()
def got_puback(pid):
    puback_set.add(pid)
suback_map = {}
def got_suback(pid, resp):
    suback_map[pid] = resp

async def wait_msg(mqc, op):
    t0 = ticks_ms()
    while ticks_diff(ticks_ms(), t0) < 1000:
        if await mqc.check_msg() == op: return

async def do_conn(clean, sub):
    print("connecting with clean={} sub={}".format(clean, sub))
    global pub_q, puback_set, suback_map, pid
    pub_q = []
    puback_set = set()
    suback_map = {}
    #
    mqc = MQTTProto(got_pub, got_puback, got_suback)
    mqc.DEBUG=1
    # connect
    await mqc.connect(broker, cli_id, clean)
    t0 = mqc.last_ack
    # give broker some time to queue some messages
    await sleep_ms(200)
    # try a ping
    await mqc.ping()
    await wait_msg(mqc, 0xd)
    await sleep_ms(200)
    if mqc.last_ack == t0:
        print("Error: did not receive ping response")
    print("pubs: {}".format([p.pid for p in pub_q]))
    # subscribe at QoS=1 if requested
    topic = prefix + 'mirror1'
    if sub:
        await mqc.subscribe(topic, 1, pid)
        await wait_msg(mqc, 9)
        if not pid in suback_map:
            print("Error: did not receive suback @qos=1")
        elif not suback_map[pid]:
            print("Error: subscribe rejected @qos=1")
        pid += 1
    # publish to above topic using QoS=1
    print("pub {}".format(pid))
    await mqc.publish(MQTTMessage(topic, "hello", qos=1, pid=pid))
    await wait_msg(mqc, 3)
    if len(pub_q) == 0:
        print("Error: did not receive mirror pub @qos=1")
    elif pub_q[-1].topic != topic.encode() or pub_q[-1].message != "hello".encode() or \
            pub_q[-1].retain != 0 or pub_q[-1].qos != 1:
        print("Error: incorrect mirror msg @qos=1", pub_q[-1])
    if not pid in puback_set:
        print("Error: did not receive puback @qos=1")
    pid += 1
    print("pubs: {}".format([p.pid for p in pub_q]))
    # disconnect
    await mqc.disconnect()
    await sleep_ms(100)

loop = asyncio.get_event_loop()

import network
sta = network.WLAN(network.STA_IF)
if not sta.isconnected():
    async def connect_wifi():
        print("connecting wifi")
        sta.active(True)
        sta.connect("tve-home", "tve@home")
        await sleep_ms(4000)
    loop.run_until_complete(connect_wifi())

# Test clean connection
async def test_clean():
    print("=== test_clean starting")
    for i in range(5):
        await do_conn(True, True)
    print("test_clean done")

loop.run_until_complete(test_clean())

# Test clean connection
async def test_unclean():
    print("=== test_unclean starting")
    await do_conn(True, True)
    await do_conn(False, True)
    for i in range(5):
        await do_conn(False, False)
    print("test_unclean done")

loop.run_until_complete(test_unclean())

# Test clean connection
async def test_mixed():
    print("=== test_mixed starting")
    await do_conn(True, True)
    for i in range(2):
        await do_conn(False, False)
    for i in range(2):
        await do_conn(False, True)
    for i in range(2):
        await do_conn(False, False)
    print("test_mixed done")

loop.run_until_complete(test_mixed())
