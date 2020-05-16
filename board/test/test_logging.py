# This test of board/logging.py resides in a subdirectory with a symlink called mplogging.py
# because having a file called logging.py in the current directory causes all hell to break loose...
import pytest
import mplogging
pytestmark = pytest.mark.timeout(10)

# stuff that exists in MP but not CPython
from time import monotonic
def ticks_ms():
    return monotonic() * 1000
def ticks_diff(a, b):
    return a - b
import asyncio
async def sleep_ms(ms):
    await asyncio.sleep(ms / 1000)


# MQTTCli is a stub for mqtt_async.MQTTClient
class MQTTCli:
    def __init__(self):
        self.sub = None
        self.pub = None

    async def subscribe(self, topic, qos=-1):
        self.sub = (topic, qos)

    async def publish(self, topic, msg, retain=False, qos=-1, sync=True):
        print("PUB", topic, msg)
        self.pub = (topic, msg, retain, qos, sync)


# Stream to collect log output
class LogStream:
    buf = b""

    def write(self, b):
        self.buf += b


def test_simple():
    s = LogStream()
    mplogging._stream = s
    l = mplogging.getLogger("simple")
    l.info("hello")
    assert s.buf.startswith(b"\033")
    assert s.buf.endswith(b"\n")
    assert b"I " in s.buf
    assert b"hello" in s.buf

def test_mqtt_log():
    s = LogStream()
    mplogging._stream = s
    ml = mplogging.MQTTLog(mplogging.INFO)
    l = mplogging.getLogger("mqtt_log")
    l.info("hello %d", 123)
    assert s.buf.startswith(b"\033")
    assert b"hello" in s.buf
    assert len(ml._q) == 1
    assert ml._q[0].startswith(b"I ")
    assert ml._q[0].endswith(b" hello 123")

def test_mqtt_buffering():
    s = LogStream()
    mplogging._stream = s
    ml = mplogging.MQTTLog(mplogging.INFO, maxsize=500)
    l = mplogging.getLogger("mqtt_log")
    for i in range(10):
        l.info(str(i) * 75)
    assert s.buf.count(b'I') == 10
    assert len(ml._q) == 5
    assert ml._q[0].endswith(b"555")
    assert ml._q[4].endswith(b"999")

def test_mqtt_long():
    s = LogStream()
    mplogging._stream = s
    ml = mplogging.MQTTLog(mplogging.INFO)
    l = mplogging.getLogger("mqtt_long")
    l.info("hello" * 30)
    assert s.buf.startswith(b"\033")
    assert b"hello" in s.buf
    assert len(ml._q[0]) == 128

@pytest.mark.asyncio
async def test_mqtt_pub():
    s = LogStream()
    mplogging._stream = s
    ml = mplogging.MQTTLog(mplogging.INFO)
    mq = MQTTCli()
    t = asyncio.get_event_loop().create_task(ml.run(mq, b"some/topic"))
    l = mplogging.getLogger("mqtt_log")
    l.info("hello %d", 987)
    assert s.buf.startswith(b"\033")
    assert b"hello" in s.buf
    await sleep_ms(50)
    assert len(ml._q) == 0
    assert mq.pub is not None
    t.cancel()
