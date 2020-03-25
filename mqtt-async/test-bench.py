# Benchmark MQTTClient in mqtt_async.py
# More specifically, verify that the streaming pub produces the desired results.
# Run this benchmark using cpython or micropython, a few changes commenting out pytest markers let
# it run under pytest as well but the only benefit is if assertions fail to see details.

import random, sys
try:
    import pytest
    pytestmark = pytest.mark.timeout(10)
except:
    pass

from mqtt_async import MQTTClient, MQTTConfig, MQTTMessage

broker = ('192.168.0.14', 1883)
cli_id = 'mqtt_async_tester'
prefix = 'esp32/tests/'

# stuff that exists in MP but not CPython
try:
    from time import ticks_ms, ticks_diff
    import uasyncio as asyncio
except:
    from time import monotonic_ns
    def ticks_ms(): return int(monotonic_ns() // 1000000)
    def ticks_diff(a, b): return a-b
    import asyncio
#async def sleep_ms(ms): await asyncio.sleep(ms/1000)

# callbacks

msg_q = []
def subs_cb(msg):
    global msg_q
    #print("got pub", msg.pid)
    msg.message = msg.message[:10]
    msg_q.append(msg)

wifi_status = None
async def wifi_coro(status):
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

# helpers

cli_num = random.randrange(100000000) # add number to client id so each test
def fresh_config():
    global cli_num, conn_calls, conn_fail
    conf = MQTTConfig()
    conf.server = broker[0]
    conf.port = broker[1]
    conf.ssid = 'tve-home'
    conf.wifi_pw = 'tve@home'
    conf.client_id = "{}-{}".format(cli_id, cli_num)
    cli_num += 1
    conf.wifi_coro = wifi_coro
    conf.subs_cb = subs_cb
    conf.connect_coro = conn_start
    return conf

async def connect_subscribe(topic, qos, clean=True):
    conf = fresh_config()
    conf.debug = 0
    conf.clean = clean
    mqc = MQTTClient(conf)
    reset_cb()
    #
    await mqc.connect()
    await asyncio.sleep_ms(10) # give created tasks a chance to run
    assert wifi_status == True
    assert conn_started == True
    await mqc.subscribe(topic, qos)
    return (mqc, conf)

async def finish_test(mqc):
    # initiate disconnect
    await mqc.disconnect()
    assert mqc._proto is None
    assert mqc._state == 2
    # wait a bit and ensure all tasks have finished
    return
    await asyncio.sleep_ms(100)
    assert mqc._conn_keeper is None
    print(asyncio.all_tasks())
    assert len(asyncio.all_tasks()) == 1

# benchmark streaming pub
#@pytest.mark.asyncio
async def test_bench_pub(forceSync=False):
    topic = (prefix+"bench1").encode()
    mqc, conf = await connect_subscribe(prefix+"x", 1, clean=True)
    #
    num = 100
    sz = 1400
    print("Starting to {} pub {} messages".format("blocking" if forceSync else "streaming", num))
    m = bytearray(sz)
    t0 = ticks_ms()
    for i in range(num):
        m[0] = i+1
        sync = i == num-1 or forceSync
        await mqc.publish(topic, m, qos=1, sync=sync)
    #
    dt = ticks_diff(ticks_ms(), t0)
    by = num * sz
    print("Took {}ms {:.3f}kB/s {}kbps, got {} messages".format(dt, by/dt, by*8/dt, len(msg_q)))
    assert len(msg_q) == 0
    #
    await finish_test(mqc)

# benchmark streaming pub-sub
#@pytest.mark.asyncio
async def test_bench_pubsub(forceSync=False):
    topic = prefix+"bench2"
    mqc, conf = await connect_subscribe(topic, 1, clean=True)
    #
    num = 100
    sz = 1400
    print("Starting to {} pub-sub {} messages".format("blocking" if forceSync else "streaming", num))
    m = bytearray(sz)
    t0 = ticks_ms()
    for i in range(num):
        m[0] = i+1
        sync = i == num-1 or forceSync
        await mqc.publish(topic, m, qos=1, sync=sync)
    #
    dt = ticks_diff(ticks_ms(), t0)
    by = num * sz * 2
    await asyncio.sleep_ms(100)
    print("Took {}ms {:.3f}kB/s {}kbps, got {} messages".format(dt, by/dt, by*8/dt, len(msg_q)))
    assert len(msg_q) >= num
    assert msg_q[0].message[0] == 1
    assert msg_q[len(msg_q)-1].message[0] == num
    #
    await finish_test(mqc)

import gc
gc.collect()
loop = asyncio.get_event_loop()
loop.run_until_complete(test_bench_pub(False))
loop.run_until_complete(test_bench_pub(True))
loop.run_until_complete(test_bench_pubsub(False))
loop.run_until_complete(test_bench_pubsub(True))
