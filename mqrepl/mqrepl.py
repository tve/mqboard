# MQTT Repl for MicroPython by Thorsten von Eicken (c) 2020
#
# Requires mqtt_async for asyncio-based MQTT.

import io, os, sys, time, board, struct, gc
from mqtt_async import MQTTClient, config
from esp32 import Partition
import uasyncio as asyncio
import uhashlib as hashlib
import ubinascii as binascii
#asyncio.set_debug(True)
#asyncio.core.set_debug(True)
import logging
log = logging.getLogger(__name__)
log.setLevel(logging.DEBUG)

TOPIC = 'esp32/mqb/' + board.location + "/"
TOPIC_CMD = TOPIC + "cmd/"
BUFLEN=2800 # data bytes to make message fit into two std TCP segments
BLOCKLEN = const(4096) # data bytes in a flash block
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
    async def handle(self, sha, msg, seq, last):
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
            self.buf[self.buflen:BLOCKLEN] = msg[:cpylen]
            self.part.writeblocks(self.block, self.buf)
            self.block += 1
            msglen -= cpylen
            if msglen > 0:
                self.buf[:msglen] = msg[cpylen:]
            self.buflen = msglen
        else:
            self.buf[self.buflen:self.buflen+msglen] = msg
            self.buflen += msglen
            if last and self.buflen > 0:
                for i in range(BLOCKLEN-self.buflen):
                    self.buf[self.buflen+i] = 0xff # erased flash is ff
                self.part.writeblocks(self.block, self.buf)
                self.block += 1
        assert len(self.buf) == BLOCKLEN
        if last:
            return await self.finish(sha)
        elif (seq&7) == 0:
            #print("Sending ACK {}".format(seq))
            return "SEQ {}".format(seq).encode()

    async def finish(self, check_sha):
        del self.buf
        self.seq = None
        calc_sha = binascii.hexlify(self.sha.digest())
        check_sha = check_sha.encode()
        if calc_sha != check_sha:
            raise ValueError("SHA mismatch calc:{} check={}".format(calc_sha, check_sha))
        print("set_boot")
        self.part.set_boot()
        return b'OK'


class MQRepl:
    def __init__(self):
        self._mqclient = None
        self._ota = None
        self._put_fd = None
        self._put_seq = None
        self.CMDS = { 'eval': self._do_eval, 'exec': self._do_exec, 'get': self._do_get,
                'put': self._do_put, 'ota': self._do_ota }

    async def start(self, config):
        board.blue_led(True) # signal that we're connecting, will get turned off by pulse()
        #config['ssl_params'] = {'psk_ident':board.mqtt_ident, 'psk_key':board.mqtt_key}
        config.subs_cb = self._sub_cb
        config.wifi_coro = self._wifi_cb
        config.debug = 1
        # get a clean connection
        config.clean = True
        self._mqclient = MQTTClient(config)
        await self._mqclient.connect()
        await self._mqclient.disconnect()
        # now do real connection
        config.clean = False
        config.connect_coro = self._conn_cb
        self._mqclient = MQTTClient(config)
        await self._mqclient.connect()

    async def stop(self):
        await self._mqclient.disconnect()
        self._mqclient = None

    async def watchdog(self):
        while self._mqclient:
            await asyncio.sleep(60)
            log.info("Still watching...")

    async def run(self, config):
        await self.start(config)
        await self.watchdog()

    # Handlers for commands

    # do_eval receives an expression in cmd, runs it through the interpreter and returns
    # the result using repr()
    async def _do_eval(self, fname, cmd, seq, last):
        if seq != 0 or not last:
            raise ValueError(ERR_SINGLEMSG)
        cmd = str(cmd, 'utf-8')
        log.debug("eval %s", cmd)
        op = compile(cmd, "<eval>", "eval")
        result = eval(op, globals(), None)
        return repr(result)

    # do_exec receives a command line in cmd, runs it through the interpreter and returns
    # the resulting output
    async def _do_exec(self, fname, cmd, seq, last):
        if seq != 0 or not last:
            raise ValueError(ERR_SINGLEMSG)
        cmd = str(cmd, 'utf-8')
        log.debug("exec %s", cmd)
        outbuf = io.BytesIO(BUFLEN)
        old_term = os.dupterm(outbuf)
        try:
            op = compile(cmd, "<exec>", "exec")
            eval(op, globals(), None)
            await asyncio.sleep_ms(10)
            os.dupterm(old_term)
            return outbuf.getvalue()
        except Exception:
            os.dupterm(old_term)
            raise

    # do_get opens the file fname and retuns it as a stream so it can be sent back
    async def _do_get(self, fname, msg, seq, last):
        if seq != 0 or not last:
            raise ValueError(ERR_SINGLEMSG)
        log.debug("opening {}".format(fname))
        return open(fname, 'rb')

    # do_put opens the file fname for writing and appends the message content to it.
    async def _do_put(self, fname, msg, seq, last):
        if seq == 0:
            if self._put_fd != None: self._put_fd.close()
            self._put_fd = open(fname, 'wb')
            self._put_seq = 1 # next seq expected
        elif self._put_seq is None:
            raise ValueError("missing first message")
        elif self._put_seq < seq:
            # "duplicate message"
            return None
        elif self._put_seq > seq:
            raise ValueError("message missing")
        else:
            self._put_seq += 1
        self._put_fd.write(msg[2:])
        if last:
            self._put_fd.close()
            self._put_fd = None
            self._put_seq = None
            return b"OK"
        return None

    # do_ota uploads a new firmware over-the-air and activates it for the next boot
    # the fname passed in must be the sha256 of the firmware
    async def _do_ota(self, fname, msg, seq, last):
        if seq == 0:
            self._ota = OTA()
        if self._ota is not None:
            ret = await self._ota.handle(fname, msg, seq, last)
            if last:
                self._ota = None
                gc.collect()
            return ret

    # Helpers

    async def _send_stream(self, topic, stream):
        buf = bytearray(BUFLEN+2)
        buf[2:] = stream.read(BUFLEN)
        seq = 0
        last = 0
        while True:
            last = len(buf) == 2
            struct.pack_into("!H", buf, 0, last<<15 | seq)
            log.debug("pub {} -> {}".format(len(buf), topic))
            await self._mqclient.publish(topic, buf, qos=1, sync=last)
            if last:
                stream.close()
                return None
            buf[2:] = stream.read(BUFLEN)
            seq += 1

    # pulse blue LED
    async def _pulse(self):
        board.blue_led(True)
        await asyncio.sleep_ms(100)
        board.blue_led(False)

    # mqtt_async callback handlers

    tl = 0

    # handle the arrival of an MQTT message
    # The first two bytes of each message contain a binary (big endian) sequence number with the top
    # bit set for the last message in the sequence.
    async def _sub_cb(self, topic, msg, retained, qos):
        topic = str(topic, 'utf-8')
        #log.debug("MQTT: %s", topic)
        loop = asyncio.get_event_loop()
        loop.create_task(self._pulse())
        if topic.startswith(TOPIC_CMD) and len(msg) >= 2:
            # expect topic: TOPIC/cmd/<cmd>/<id>[/<filename>]
            topic = topic[len(TOPIC_CMD):].split("/", 2)
            if len(topic) < 2: return
            cmd, ident, *name = topic
            name = name[0] if len(name) else None
            rtopic = TOPIC + "reply/out/" + ident
            errtopic = TOPIC + "reply/err/" + ident
            # parse message header (first two bytes)
            seq = ((msg[0] & 0x7f) << 8) | msg[1]
            last = (msg[0] & 0x80) != 0
            msg = msg[2:]
            try:
                fun = self.CMDS[cmd]
                dt = time.ticks_diff(time.ticks_ms(), self.tl)
                log.info("dispatch: fun={}, msglen={} seq={} last={} id={} dt={}".format(fun.__name__,
                    len(msg), seq, last, ident, dt))
                try:
                    t0 = time.ticks_ms()
                    resp = await fun(name, msg, seq, last)
                    log.debug("took {}ms".format(time.ticks_diff(time.ticks_ms(), t0)))
                    self.tl = time.ticks_ms()
                    if resp is None:
                        pass
                    elif callable(getattr(resp, "read", None)):
                        loop.create_task(self._send_stream(rtopic, resp))
                    else:
                        log.debug("pub {} -> {}".format(len(resp), rtopic))
                        loop.create_task(self._mqclient.publish(rtopic, b'\x80\0' + resp, qos=1))
                except ValueError as e:
                    buf = "MQRepl protocol error {}: {}".format(cmd, e.args[0])
                    loop.create_task(self._mqclient.publish(errtopic, buf, qos=1))
                except Exception as e:
                    errbuf = io.BytesIO(1400)
                    sys.print_exception(e, errbuf)
                    errbuf = errbuf.getvalue()
                    log.warning("Exception: <<%s>>", errbuf)
                    loop.create_task(self._mqclient.publish(errtopic, errbuf, qos=1))
            except KeyError:
                loop.create_task(self._mqclient.publish(errtopic, "Command '" + cmd + "' not supported", qos=1))

    async def _wifi_cb(self, state):
        board.wifi_led(not state)  # Light LED when WiFi down
        if state:
            log.info('WiFi connected')
        else:
            log.info('WiFi or broker is down')

    async def _conn_cb(self, client):
        log.info('MQTT connected')
        await client.subscribe(TOPIC+"cmd/#", qos=1)
        log.info("Subscribed to %s%s", TOPIC, "cmd/#")

def doit():
    print("\n===== esp32 mqttrepl at `{}` starting at {} =====\n".format(board.location, time.time()))
    logging.basicConfig(level=logging.INFO)
    ll=logging;ll._level_dict={ll.CRITICAL:'C',ll.ERROR:'E',ll.WARNING:'W',ll.INFO:'I',ll.DEBUG:'D'}
    mqr = MQRepl()
    asyncio.run(mqr.run(config))

if __name__ == '__main__': doit()
