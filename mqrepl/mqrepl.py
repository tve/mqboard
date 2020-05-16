# MQTT Repl for MicroPython by Thorsten von Eicken (c) 2020
#
# Requires mqtt_async for asyncio-based MQTT.

import io, os, sys, time, struct, gc, micropython
from esp32 import Partition
import uasyncio as asyncio
from uasyncio import Loop
import uhashlib as hashlib
import ubinascii as binascii
import logging

log = logging.getLogger(__name__)
# log.setLevel(logging.DEBUG)

TOPIC = "esp32/test/mqb/"  # typ. overridden in MQRepl's constructor
PKTLEN = 1400  # data bytes that reasonably fit into a TCP packet
BUFLEN = PKTLEN * 2  # good number of data bytes to stream files
BLOCKLEN = const(4096)  # data bytes in a flash block
ERR_SINGLEMSG = "only single message supported"

# OTA manages a MicroPython firmware update over-the-air.
# It assumes that there are two "app" partitions in the partition table and updates the one
# that is not currently running. When the update is complete, it sets the new partition as
# the next one to boot. It does not reset/restart, use machine.reset().
class OTA:
    def __init__(self):
        self.part = Partition(Partition.RUNNING).get_next_update()
        self.sha = hashlib.sha256()
        self.seq = 0
        self.block = 0
        self.buf = bytearray(BLOCKLEN)
        self.buflen = 0

    # handle processes one message with a chunk of data in msg. The sequence number seq needs
    # to increment sequentially and the last call needs to have last==True as well as the
    # sha set to the hashlib.sha256(entire_data).hexdigest().
    def handle(self, sha, msg, seq, last):
        if self.seq is None:
            raise ValueError("missing first message")
        elif self.seq < seq:
            # "duplicate message"
            return None
        elif self.seq > seq:
            raise ValueError("message missing")
        else:
            self.seq += 1
        self.sha.update(msg)
        # avoid allocating memory: use buf as-is
        msglen = len(msg)
        if self.buflen + msglen >= BLOCKLEN:
            # got a full block, assemble it and write to flash
            cpylen = BLOCKLEN - self.buflen
            self.buf[self.buflen : BLOCKLEN] = msg[:cpylen]
            self.part.writeblocks(self.block, self.buf)
            self.block += 1
            msglen -= cpylen
            if msglen > 0:
                self.buf[:msglen] = msg[cpylen:]
            self.buflen = msglen
        else:
            self.buf[self.buflen : self.buflen + msglen] = msg
            self.buflen += msglen
            if last and self.buflen > 0:
                for i in range(BLOCKLEN - self.buflen):
                    self.buf[self.buflen + i] = 0xFF  # erased flash is ff
                self.part.writeblocks(self.block, self.buf)
                self.block += 1
        assert len(self.buf) == BLOCKLEN
        if last:
            return self.finish(sha)
        elif (seq & 7) == 0:
            # print("Sending ACK {}".format(seq))
            return "SEQ {}".format(seq).encode()

    def finish(self, check_sha):
        del self.buf
        self.seq = None
        calc_sha = binascii.hexlify(self.sha.digest())
        check_sha = check_sha.encode()
        if calc_sha != check_sha:
            raise ValueError("SHA mismatch calc:{} check={}".format(calc_sha, check_sha))
        print("set_boot")
        self.part.set_boot()
        return "OK"


# Stream interface to pass to dupterm. It is used to collect output from the repl, or
# more precisely, from sys.stdout  It does not feed any input to the repl because that's pointless
# as the repl is stuck waiting for the uasyncio loop to finish and thus doesn't process any input.
class ReplStream(io.IOBase):

    # Create a repl interface and start publishing repl output using the pub function passed as
    # argument. Pub must accept a byte buffer.
    def __init__(self):
        self.tx_buf = bytearray(PKTLEN)
        self.tx_len = 0
        self.ev = asyncio.Event()

    def read(self, sz=None):
        return None

    def readinto(self, buf):
        return None

    def ioctl(self, op, arg):
        return 0

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
                    tx = self.tx_buf[: self.tx_len]
                    self.tx_len = 0
                    if len(self.tx_buf) > PKTLEN:
                        self.tx_buf = bytearray(PKTLEN)
                    await pub(tx)
                # else:
                #    await pub("Nothing...\n")
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
        # if buf[:5] == "TADA:": return
        # print("TADA: {}\n".format(str(buf, "utf-8")), end='')
        tx_len = self.tx_len
        lb = len(buf)
        if lb <= PKTLEN - tx_len:
            # buf fits into tx_buf: copy it
            self.tx_buf[tx_len : tx_len + lb] = buf
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
        if tx_len > PKTLEN * 3 // 4:
            self.ev.set()
        self.tx_len = tx_len
        return lb


class MQRepl:
    def __init__(self, mqtt, config=None):
        global TOPIC, TOPIC_CMD
        self._ota = None
        self._put_fd = None
        self._put_seq = None
        self._repl_task = None
        self._ndup = False  # set true when 1st non-dup msg is received
        self.CMDS = {
            "eval": self._do_eval,
            "exec": self._do_exec,
            "get": self._do_get,
            "put": self._do_put,
            "ota": self._do_ota,
        }
        if config:
            TOPIC = config["prefix"] + "/mqb/"
        TOPIC_CMD = TOPIC + "cmd/"
        self.mqclient = mqtt.client
        mqtt.on_connect(self.start)
        mqtt.on_msg(self._msg_cb)

    async def _ttypub(self, buf):
        if self.mqclient:
            await self.mqclient.publish(TOPIC + "ttyout", buf, qos=1, sync=False)

    async def start(self, client):
        topic = TOPIC + "cmd/#"
        await client.subscribe(topic, qos=1)
        log.info("Subscribed to %s", topic)
        # capture stdout
        # if not self._repl_task:
        #    ttyout = ReplStream()
        #    self._repl_task = Loop.create_task(ttyout.sender(self._ttypub))
        #    os.dupterm(ttyout)

    def stop(self):
        if self._repl_task:
            self._repl_task.cancel()
            self._repl_task = None
        self.mqclient = None
        os.dupterm(None)

    # Handlers for commands

    # do_eval receives an expression in cmd, runs it through the interpreter and returns
    # the result using repr()
    def _do_eval(self, fname, cmd, seq, last):
        if seq != 0 or not last:
            raise ValueError(ERR_SINGLEMSG)
        cmd = str(cmd, "utf-8")
        log.debug("eval %s", cmd)
        op = compile(cmd, "<eval>", "eval")
        result = eval(op, globals(), None)
        return repr(result)

    # do_exec receives a command line in cmd, runs it through the interpreter and returns
    # the resulting output
    def _do_exec(self, fname, cmd, seq, last):
        if seq != 0 or not last:
            raise ValueError(ERR_SINGLEMSG)
        cmd = str(cmd, "utf-8")
        log.debug("exec %s", cmd)
        outbuf = io.BytesIO(BUFLEN)
        old_term = os.dupterm(outbuf)
        try:
            op = compile(cmd, "<exec>", "exec")
            eval(op, globals(), None)
            time.sleep_ms(5)  # necessary to capture all output?
            return outbuf.getvalue()
        finally:
            os.dupterm(old_term)

    # do_get opens the file fname and retuns it as a stream so it can be sent back
    def _do_get(self, fname, msg, seq, last):
        if seq != 0 or not last:
            raise ValueError(ERR_SINGLEMSG)
        log.debug("opening {}".format(fname))
        return open(fname, "rb")

    # do_put opens the file fname for writing and appends the message content to it.
    def _do_put(self, fname, msg, seq, last):
        if seq == 0:
            if self._put_fd != None:
                self._put_fd.close()
            self._put_fd = open(fname, "wb")
            self._put_seq = 1  # next seq expected
        elif self._put_seq is None:
            raise ValueError("missing first message")
        elif seq < self._put_seq:
            # "duplicate message"
            return None
        elif seq > self._put_seq:
            raise ValueError("message missing: {} vs. {}".format(seq, self._put_seq))
        else:
            self._put_seq += 1
        self._put_fd.write(msg)
        if last:
            self._put_fd.close()
            self._put_fd = None
            self._put_seq = None
            return "OK"
        return None

    # do_ota uploads a new firmware over-the-air and activates it for the next boot
    # the fname passed in must be the sha256 of the firmware
    def _do_ota(self, fname, msg, seq, last):
        if seq == 0:
            self._ota = OTA()
        if self._ota is not None:
            ret = await self._ota.handle(fname, msg, seq, last)
            if last:
                self._ota = None
            return ret

    # Helpers

    async def _send_stream(self, topic, stream):
        buf = bytearray(BUFLEN + 2)
        buf[2:] = stream.read(BUFLEN)
        seq = 0
        last = 0
        while True:
            last = len(buf) == 2
            struct.pack_into("!H", buf, 0, last << 15 | seq)
            log.debug("pub {} -> {}".format(len(buf), topic))
            await self.mqclient.publish(topic, buf, qos=1, sync=last)
            if last:
                stream.close()
                return None
            buf[2:] = stream.read(BUFLEN)
            seq += 1

    # mqtt_async callback handlers

    tl = 0

    # handle the arrival of an MQTT message
    # The first two bytes of each message contain a binary (big endian) sequence number with the top
    # bit set for the last message in the sequence.
    def _msg_cb(self, topic, msg, retained, qos, dup):
        topic = str(topic, "utf-8")
        # log.info("MQTT: %s", topic)
        if topic.startswith(TOPIC_CMD) and len(msg) >= 2:
            if dup and not self._ndup:
                # skip inital dup msg: they may be unacked 'cause they may have crashed us
                return
            else:
                self._ndup = True
            # expect topic: TOPIC/cmd/<cmd>/<id>[/<filename>]
            topic = topic[len(TOPIC_CMD) :].split("/", 2)
            if len(topic) < 2:
                return
            cmd, ident, *name = topic
            name = name[0] if len(name) else None
            rtopic = TOPIC + "reply/out/" + ident
            errtopic = TOPIC + "reply/err/" + ident
            # parse message header (first two bytes)
            seq = ((msg[0] & 0x7F) << 8) | msg[1]
            last = (msg[0] & 0x80) != 0
            msg = memoryview(msg)[2:]
            try:
                fun = self.CMDS[cmd]
                dt = time.ticks_diff(time.ticks_ms(), self.tl)
                log.info(
                    "dispatch: fun={}, msglen={} seq={} last={} id={} dup={} dt={}".format(
                        fun.__name__, len(msg), seq, last, ident, dup, dt
                    )
                )
                try:
                    t0 = time.ticks_ms()
                    resp = fun(name, msg, seq, last)
                    log.debug("took {}ms".format(time.ticks_diff(time.ticks_ms(), t0)))
                    self.tl = time.ticks_ms()
                    if resp is None:
                        pass
                    elif callable(getattr(resp, "read", None)):
                        Loop.create_task(self._send_stream(rtopic, resp))
                    else:
                        log.debug("pub {} -> {}".format(len(resp), rtopic))
                        Loop.create_task(self.mqclient.publish(rtopic, b"\x80\0" + resp, qos=1))
                except ValueError as e:
                    buf = "MQRepl protocol error {}: {}".format(cmd, e.args[0])
                    Loop.create_task(self.mqclient.publish(errtopic, buf, qos=1))
                except Exception as e:
                    errbuf = io.BytesIO(1400)
                    sys.print_exception(e, errbuf)
                    errbuf = errbuf.getvalue()
                    log.warning("Exception: <<%s>>", errbuf)
                    micropython.mem_info()
                    Loop.create_task(self.mqclient.publish(errtopic, errbuf, qos=1))
            except KeyError:
                Loop.create_task(
                    self.mqclient.publish(errtopic, "Command '" + cmd + "' not supported", qos=1)
                )


def start(mqtt, config):
    mqr = MQRepl(mqtt, config)


# def doit():
#    mqr = MQRepl(config)
#    Loop.create_task(mqr.start())
#    Loop.run_forever()
#
# if __name__ == '__main__': doit()
