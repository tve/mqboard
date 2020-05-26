# MQTT Repl for MicroPython
# Copyright © 2020 by Thorsten von Eicken.
#
# Requires mqtt_async for asyncio-based MQTT.

import io, os, sys, time, struct, gc, micropython
from esp32 import Partition
from uasyncio import Loop as loop
import uhashlib as hashlib
import ubinascii as binascii
import logging

log = logging.getLogger(__name__)
# log.setLevel(logging.DEBUG)

TOPIC = "esp32/test/mqb/"  # typ. overridden in MQRepl's constructor (exported to other modules)
PKTLEN = 1400  # data bytes that reasonably fit into a TCP packet
BUFLEN = PKTLEN * 2  # good number of data bytes to stream files
BLOCKLEN = const(4096)  # data bytes in a flash block
ERR_SINGLEMSG = "only single message supported"

# OTA manages a MicroPython firmware update over-the-air.
# It assumes that there are two "app" partitions in the partition table and updates the one
# that is not currently running. When the update is complete, it sets the new partition as
# the next one to boot. It does not reset/restart, use machine.reset() explicitly.
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
        self.part.set_boot()
        return "OK"


# LogWriter is a helper class that sends text line-wise to a logger (logging module).
#class LogWriter(io.IOBase):
#    def __init__(self, logger, level):
#        self._logger = logger
#        self._level = level
#        self._wbuf = b""
#
#    def write(self, buf):
#        if buf == b"":
#            return
#        lines = (self._wbuf + buf).split(b"\n")
#        self._wbuf = lines[-1]
#        for l in lines[:-1]:
#            self._logger(self._level, l)


# MQRepl implements REPL-like functionality over MQTT. It receives command messages, performs
# the commands, and sends a response back.
# The commands topics have the general form .../cmd/<cmd>/<id>[/<filename>] where <cmd> is the name
# of the command, <id> is random ID to tie request topics and response topics for one command
# invocations together, <filename> is a filesystem path where appropriate. Responses have the
# general form .../reply/<kind>/<id> where <kind> is out and err and the <id> matches the
# request.
# The payloads contain file data, command text, or response text. Each payload is prefixed with
# a 2-byte header which contains a sequence number (to detect duplicates) and a last-message
# flag.
# All multi-message sequences must be sent using QoS=1 to ensure in-order delivery.
# A non-obvious trick is that at start-up MQRepl ignores all command messages that are
# MQTT duplicates because they may be unacked because they caused a crash and chances are
# they'll do that again (oops).
class MQRepl:
    def __init__(self, mqclient, topic):
        import __main__

        global TOPIC
        self._ota = None  # OTA in progress
        self._put_fd = None  # file descr for PUT in progress
        self._put_seq = None  # next expected PUT message seq number
        self._ndup = False  # set true when 1st non-dup msg is received
        self._globals = __main__.GLOBALS()
        TOPIC = topic
        self.mqclient = mqclient

    async def _ttypub(self, buf):
        if self.mqclient:
            await self.mqclient.publish(TOPIC + "ttyout", buf, qos=1, sync=False)

    async def start(self, mqtt):
        mqtt.on_msg(self._msg_cb)
        topic = TOPIC + "cmd/#"
        await mqtt.client.subscribe(topic, qos=1)  # TODO: should this be made async?
        log.info("Subscribed to %s", topic)

    #def stop(self):
    #    # TODO: this should unsubscribe and remove the on_msg handler, but is this ever used?
    #    pass

    # Handlers for commands

    # do_eval receives an expression in cmd, runs it through the interpreter and returns
    # the result using repr()
    def _do_eval_xx(self, fname, cmd, seq, last):
        if seq != 0 or not last:
            raise ValueError(ERR_SINGLEMSG)
        cmd = str(cmd, "utf-8")
        log.debug("eval %s", cmd)
        op = compile(cmd, "<eval>", "eval")
        result = eval(op, globals(), None)
        return repr(result)

    # do_exec receives a command line in cmd, runs it through the interpreter and returns
    # the resulting output
    def _do_exec_xx(self, fname, cmd, seq, last):
        if seq != 0 or not last:
            raise ValueError(ERR_SINGLEMSG)
        cmd = str(cmd, "utf-8")
        log.debug("exec %s", cmd)
        outbuf = io.BytesIO(BUFLEN)  # FIXME: need to stream output back
        old_term = os.dupterm(outbuf)
        try:
            op = compile(cmd, "<exec>", "exec")
            eval(op, globals(), None)
            time.sleep_ms(5)  # necessary to capture all output?
            return outbuf.getvalue()
        finally:
            os.dupterm(old_term)

    def _do_eval(self, fname, cmd, seq, last):  # read_msg, msg_len):
        if seq != 0 or not last:
            raise ValueError(ERR_SINGLEMSG)
        cmd = str(cmd, "utf-8")
        log.debug("eval %s", cmd)
        # try to eval
        try:
            op = compile(cmd, "<eval>", "eval")
            result = eval(op, self._globals, None)
            return repr(result)
        except SyntaxError:
            pass
        # try to exec
        outbuf = io.BytesIO(BUFLEN)  # FIXME: make this variable-sized with a max
        old_term = os.dupterm(outbuf)
        try:
            op = compile(cmd, "<exec>", "exec")
            exec(op, self._globals, None)
            time.sleep_ms(11)  # necessary to capture all output?
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
    # FIXME: properly guard against concurrent PUTs
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

    # do_ota uploads a new firmware over-the-air and activates it for the next boot
    # the fname passed in must be the sha256 of the firmware
    def _do_ota(self, fname, msg, seq, last):
        if seq == 0:
            self._ota = OTA()
        if self._ota is not None:
            ret = self._ota.handle(fname, msg, seq, last)
            if last:
                self._ota = None
            gc.collect()  # needed!
            return ret

    # Helpers

    # _send_stream repeatedly calls read() on the stream until EOF and publishes the data it gets
    # to the specified topic. Each packet has the std 2-byte header.
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

    # Callback handlers

    # _msg_cb handles the arrival of an MQTT message.
    # The first two bytes of each message contain a binary (big endian) sequence number with the
    # top bit set for the last message in the sequence.
    def _msg_cb(self, topic, msg, retained, qos, dup):
        topic = str(topic, "utf-8")
        # log.info("MQTT: %s", topic)
        lt = len(TOPIC)
        if topic.startswith(TOPIC) and topic[lt : lt + 4] == "cmd/" and len(msg) >= 2:
            if dup and not self._ndup:
                return  # skip inital dup msgs
            else:
                self._ndup = True
            # expect topic: TOPIC/cmd/<cmd>/<id>[/<filename>]
            topic = topic[lt + 4 :].split("/", 2)
            if len(topic) < 2:
                return
            cmd, ident, *name = topic  # *name allows for it to be missing
            name = name[0] if len(name) else None
            rtopic = TOPIC + "reply/out/" + ident
            errtopic = TOPIC + "reply/err/" + ident
            # check cmd
            fn = "_do_" + cmd
            if not hasattr(self, fn):
                loop.create_task(
                    self.mqclient.publish(errtopic, "Command '" + cmd + "' not supported", qos=1)
                )
                return
            # parse message header (first two bytes)
            seq = ((msg[0] & 0x7F) << 8) | msg[1]
            last = (msg[0] & 0x80) != 0
            msg = memoryview(msg)[2:]
            # dispatch to command function
            # logging: if something is being streamed to us and we try to send a log message back
            # for each inbound message we end up loosing log messages because we can't get them out
            # as fast as new ones arrive. This always happens during OTA. Hence we stop logging
            # every message...
            if seq < 4 or last or seq & 0xf == 0:
                log.info(
                    "Dispatch %s, msglen=%d seq=%d last=%s id=%s dup=%s",
                    cmd,
                    len(msg),
                    seq,
                    last,
                    ident,
                    dup,
                )
            try:
                t0 = time.ticks_ms()
                resp = getattr(self, fn)(name, msg, seq, last)
                log.debug("took %dms", time.ticks_diff(time.ticks_ms(), t0))
                # send response back, which may require reading a stream
                if resp is None:
                    pass
                elif callable(getattr(resp, "read", None)):
                    loop.create_task(self._send_stream(rtopic, resp))
                else:
                    log.debug("pub {} -> {}".format(len(resp), rtopic))
                    loop.create_task(self.mqclient.publish(rtopic, b"\x80\0" + resp, qos=1))
            except ValueError as e:
                buf = "MQRepl protocol error {}: {}".format(cmd, e.args[0])
                loop.create_task(self.mqclient.publish(errtopic, buf, qos=1))
            except Exception as e:
                log.warning("Exception in %s: %s", cmd, e)
                #lw = LogWriter(log.log, logging.WARNING)
                #sys.print_exception(e, lw)
                errbuf = io.BytesIO(PKTLEN)
                sys.print_exception(e, errbuf)
                errbuf = errbuf.getvalue()
                loop.create_task(self.mqclient.publish(errtopic, errbuf, qos=1))
                #micropython.mem_info()


def start(mqtt, config):
    mqr = MQRepl(mqtt.client, config["prefix"])
    mqtt.on_init(mqr.start(mqtt))
