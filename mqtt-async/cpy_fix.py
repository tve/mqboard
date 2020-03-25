# work-arounds on cpython to enable pytest testing of mqtt_as.py

from time import monotonic_ns
def ticks_ms(): return monotonic_ns() // 1000000
def ticks_diff(a, b): return a-b

import asyncio

from warnings import warn

def const(x): return x
def unique_id(): return b'\xbe\xef\xf0\x0d'
import inspect
def is_awaitable(f): return inspect.isawaitable(f)

async def async_sleep_ms(ms): await asyncio.sleep(ms/1000)
asyncio.sleep_ms = async_sleep_ms

class StreamReadWriter:
    def __init__(self, sr, sw):
        self.sr = sr
        self.sw = sw
    async def read(self, n): return await self.sr.read(n)
    def write(self, b): self.sw.write(b)
    async def drain(self): await self.sw.drain()
    def close(self): self.sw.close()
    async def wait_closed(self): await self.sw.wait_closed()

async def open_connection(addr):
    (sr, sw) = await asyncio.open_connection(addr[0], addr[1])
    return StreamReadWriter(sr, sw)

class __interface:
    def __init__(self): self.connected = False
    def connect(self, ssid, pwd, listen_interval=3): self.connected = True
    def disconnect(self): self.connected = False
    def isconnected(self): return self.connected
    def active(self, on): pass
    def status(self): return 1
class network:
    STAT_CONNECTING = 2
STA_IF = __interface()
