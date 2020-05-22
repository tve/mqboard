# MQTT Logger for MicroPython by Thorsten von Eicken (c) 2020
#
# Requires mqtt_async for asyncio-based MQTT.

#!!!!!!!!!! This code was pulled out of mqrepl and is not finished. It's probably better to
#!!!!!!!!!! hook Logging and make sure all errors and exceptions result in calls to Logging.
#!!!!!!!!!! This way verbosity can be controlled and the line oriented nature makes it easier
#!!!!!!!!!! to parse.

import io, os
import uasyncio as asyncio
from uasyncio import Loop
import logging
log = logging.getLogger(__name__)
log.setLevel(logging.DEBUG)

TOPIC = "esp32/test/logger/"  # typ. overridden in MQRepl's constructor
PKTLEN=1400      # data bytes that reasonably fit into a TCP packet
BUFLEN=PKTLEN*2  # good number of data bytes to stream files

# MqLogger sends the standard MicroPython output to an MQTT topic.
# Stream interface to pass to dupterm. It is used to collect output from the repl, or
# more precisely, from sys.stdout  It does not feed any input to the repl because that's pointless
# as the repl is stuck waiting for the uasyncio loop to finish and thus doesn't process any input.
class MqLogger(io.IOBase):

    # Create a repl interface and start publishing repl output using the pub function passed as
    # argument. Pub must accept a byte buffer.
    def __init__(self):
        self.tx_buf = bytearray(PKTLEN)
        self.tx_len = 0
        self.ev = asyncio.Event()

    def read(self, sz=None): return None
    def readinto(self, buf): return None
    def ioctl(self, op, arg): return 0

    # sender should be started as a background task so it can tick away and
    # publish buffered data. It deliberately sleeps for 100ms and delays sending stuff so
    # there is a chance to stuff more per packet.
    # pub should be an async function that takes a bytes argument
    async def sender(self, pub):
        Loop.create_task(self._ticker())
        while True:
            try:
                # publish what we've got
                if self.tx_len > 0:
                    tx = self.tx_buf[:self.tx_len]
                    self.tx_len = 0
                    if len(self.tx_buf) > PKTLEN:
                        self.tx_buf = bytearray(PKTLEN)
                    await pub(tx)
                #else:
                #    await pub(b"Nothing...\n")
                # wait for event so we send more
                await self.ev.wait()
                self.ev.clear()
            except Exception:
                await asyncio.sleep(200)

    async def _ticker(self):
        while True:
            self.ev.set()
            await asyncio.sleep_ms(100)

    def write(self, buf):
        #if buf[:5] == b"TADA:": return
        #print("TADA: {}\n".format(str(buf, "utf-8")), end='')
        tx_len = self.tx_len
        lb = len(buf)
        if lb <= PKTLEN-tx_len:
            # buf fits into tx_buf: copy it
            self.tx_buf[tx_len:tx_len+lb] = buf
            tx_len += lb
        elif lb < PKTLEN:
            # buf doesn't fit and is less than total buffer: shift over
            self.tx_buf[:-lb] = self.tx_buf[lb:]
            self.tx_buf[-lb:] = buf
            tx_len = PKTLEN
        else:
            # buf doesn't fit, only grab its tail
            self.tx_buf = buf[-PKTLEN:]
            tx_len = PKTLEN
        # if buf is more than 3/4 packet, trigger a send
        if tx_len > PKTLEN*3//4:
            self.ev.set()
        self.tx_len = tx_len
        return lb

# capture stdout
#if not self._repl_task:
#    ttyout = ReplStream()
#    self._repl_task = Loop.create_task(ttyout.sender(self._ttypub))
#    os.dupterm(ttyout)

def stop():
    if self._repl_task:
        self._repl_task.cancel()
        self._repl_task = None
    self.mqclient = None
    os.dupterm(None)

