# Simple NTP daemon for MicroPython using asyncio.
# Copyright (c) 2020 by Thorsten von Eicken
# Based on https://github.com/wieck/micropython-ntpclient by Jan Wieck
# See LICENSE file

try:
    import uasyncio as asyncio
    from sys import print_exception
except ImportError:
    import asyncio
import sys, socket, struct, time, logging

try:
    from time import time_us, settime, adjtime
except ImportError:
    # (date(2000, 1, 1) - date(1970, 1, 1)).days * 24*60*60
    UNIX_DELTA = 946684800

    def time_us():
        return int((time.time() - UNIX_DELTA) * 1000000)

    def settime(usecs):
        print("settime(%d) - a step of %d" % (usecs, time_us() - (usecs + UNIX_DELTA)))

    def adjtime(usecs):
        print("adjtime(%d) - an adjustment of %d" % (usecs, time_us() - (usecs + UNIX_DELTA)))

    from asyncio_dgram import connect as dgram_connect


log = logging.getLogger(__name__)

# (date(2000, 1, 1) - date(1900, 1, 1)).days * 24*60*60
NTP_DELTA = 3155673600

# Delta from MP Epoch of 2000/1/1 to NTP Epoch 1 of Feb 7, 2036 06:28:16 UTC
# NTP_DELTA = 1139293696

# Offsets into the NTP packet
OFF_ORIG = 24
OFF_RX = 32
OFF_TX = 40

# Poll and adjust intervals
MIN_POLL = 64  # never poll faster than every 32 seconds
MAX_POLL = 1024  # default maximum poll interval


# ntp2mp converts from NTP seconds+fraction with an Epoch 1 of Feb 7, 2036 06:28:16 UTC
# to MP microseconds with an Epoch of 2000/1/1
def ntp2mp(secs, frac):
    usec = (frac * 1000000) >> 32
    # print(secs, frac, "->", secs - NTP_DELTA, (secs - NTP_DELTA) * 1000000, usec)
    return ((secs - NTP_DELTA) * 1000000) + usec


# mp2ntp converts from MP microseconds to NTP seconds and frac
def mp2ntp(usecs):
    (secs, usecs) = divmod(usecs, 1000000)
    return (secs + NTP_DELTA, (usecs << 32) // 1000000)


# ntpclient -
#   Class implementing the uasyncio based NTP client
class SNTP:
    def __init__(self, host="pool.ntp.org", poll=MAX_POLL, max_step=1):
        self._host = host
        self._sock = None
        self._addr = None
        self._send = None
        self._recv = None
        self._close = None
        self._req_poll = poll
        self._min_poll = MIN_POLL
        self._max_step = int(max_step * 1000000)
        self._poll_task = None

    def start(self):
        self._poll_task = asyncio.get_event_loop().create_task(self._poller())

    async def stop(self):
        if self._poll_task is not None:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except:
                pass
            self._close()
            self._poll_task = None

    async def _poll(self):
        # We try to stay with the same server as long as possible. Only
        # lookup the address on startup or after errors.
        if self._sock is None:
            self._addr = socket.getaddrinfo(self._host, 123)[0][-1]
            log.debug("server %s->%s", self._host, self._addr)
            if sys.implementation.name == "micropython":
                self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                self._sock.connect(self._addr)
                stream = asyncio.StreamReader(self._sock)

                async def write_drain(pkt):
                    stream.write(pkt)
                    await stream.drain()

                self._send = write_drain
                self._recv = lambda length: stream.read(length)
                self._close = lambda: self._sock.close()
            else:
                stream = await dgram_connect(self._addr)

                async def stream_send(pkt):
                    return await stream.send(pkt)

                self._send = stream_send

                async def stream_recv(length):
                    return (await stream.recv())[0]

                self._recv = stream_recv
                self._close = lambda: stream.close()

        # Send the NTP v3 request to the server
        wbuf = bytearray(48)
        wbuf[0] = 0b00011011
        send_us = time_us()
        send_ntp = mp2ntp(send_us)
        struct.pack_into("!II", wbuf, OFF_TX, send_ntp[0], send_ntp[1])  # set tx timestamp
        await self._send(wbuf)

        # Get server reply
        while True:
            # Raises asyncio.TimeoutError on time-out
            rbuf = await asyncio.wait_for(self._recv(48), timeout=1)
            recv_us = time_us()
            # Verify it's truly a response to our request
            orig_ntp = struct.unpack_from("!II", rbuf, OFF_ORIG)  # get originate timestamp
            if orig_ntp == send_ntp:
                break

        # Calculate clock step to apply per RFC4330
        rx_us = ntp2mp(*struct.unpack_from("!II", rbuf, OFF_RX))  # get server recv timestamp
        tx_us = ntp2mp(*struct.unpack_from("!II", rbuf, OFF_TX))  # get server transmit timestamp
        delay = (recv_us - send_us) - (tx_us - rx_us)
        step = ((rx_us - send_us) + (tx_us - recv_us)) // 2

        tup = struct.unpack_from("!IIIIII", rbuf, OFF_ORIG)
        r = mp2ntp(recv_us)
        # log.debug( "orig=[%d,%x] rx=[%d,%x] tx=[%d,%x] recv=[%d,%x] -> delay=%fms step=%dus",
        #    tup[0], tup[1], tup[2], tup[3], tup[4], tup[5], r[0], r[1], delay / 1000, step)

        return (delay, step)

    async def _poller(self):
        self._status = 0
        while True:
            # print("\nperforming NTP query")
            try:
                self.status = (self._status << 1) & 0xFFFF
                (delay_us, step_us) = await self._poll()
                if step_us > self._max_step or -step_us > self._max_step:
                    # print(time.localtime())
                    (tgt_s, tgt_us) = divmod(time.time_us() + step_us, 1000000)
                    log.warning("stepping to %s", time.localtime(tgt_s))
                    settime(tgt_s, tgt_us)
                    # print(time.localtime())
                else:
                    lvl = logging.DEBUG if abs(step_us) < 10000 else logging.INFO
                    log.log(lvl, "adjusting by %dus (delay=%dus)", step_us, delay_us)
                    adjtime(step_us)
                self.status |= 1
                await asyncio.sleep(61)
            except asyncio.TimeoutError:
                log.warning("%s timed out", self._host)
                if (self._status & 0x7) == 0:
                    # Three failures in a row, force fresh DNS look-up
                    self.sock = None
                    await asyncio.sleep(11)
            except OSError as e:
                # Most likely DNS lookup failure
                log.warning("%s: %s", self._host, e)
                self.sock = None
                await asyncio.sleep(11)
            except Exception as e:
                log.error("%s", e)
                print_exception(e)
                await asyncio.sleep(121)


def start(mqtt, config):
    from utime import tzset

    tzset(config.pop("zone", "UTC+0"))

    async def on_init(config):
        ss = SNTP(**config)
        ss.start()
    mqtt.on_init(on_init(config))


# if __name__ == "__main__":
#
#     logging.basicConfig(level=logging.DEBUG)
#
#     async def runner():
#         ss = SNTP(host="192.168.0.1")
#         ss.start()
#         while True:
#             await asyncio.sleep(300)
#
#     asyncio.run(runner())
