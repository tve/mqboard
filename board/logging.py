# logging with MQTT support
# This is a modified version of the micropython-lib logging module with the addition
# of being able to log to MQTT.

import sys, io

try:
    from time import ticks_ms
    from uasyncio import Event, get_event_loop, sleep_ms
except Exception:
    from time import monotonic

    def ticks_ms():
        return monotonic() * 1000

    from asyncio import Event, get_event_loop, sleep

    async def sleep_ms(ms):
        await sleep(ms / 1000)


CRITICAL = 50
ERROR = 40
WARNING = 30
INFO = 20
DEBUG = 10
NOTSET = 0

# color the line based on severity
_color_dict = {
    CRITICAL: "\033[35;1m",  # magenta bold
    ERROR: "\033[31;1m",  # red bold
    WARNING: "\033[33;1m",  # yellow bold
    INFO: "\033[32m",  # green
    DEBUG: "\033[2m",  # faint
}
# print level as a single char at the start of the line
_level_dict = {
    CRITICAL: "C",
    ERROR: "E",
    WARNING: "W",
    INFO: "I",
    DEBUG: "D",
}

_dup = None
_stream = sys.stderr


class Logger(io.IOBase):

    level = NOTSET

    def __init__(self, name):
        self.name = name
        self.wbuf = b""

    def _level_str(self, level):
        l = _level_dict.get(level)
        if l is not None:
            return l
        return "LVL%d" % level

    def setLevel(self, level):
        self.level = level

    def isEnabledFor(self, level):
        return level >= (self.level or _level)

    def log(self, level, msg, *args):
        t = ticks_ms() % 100000000
        if level < (self.level or _level):
            return
        # prep full text
        line = "%s %d %8s: " % (self._level_str(level), t, self.name)
        if args:
            msg = msg % args
        if not isinstance(msg, str):
            line = line.encode("utf-8") + msg
        else:
            line += msg
        del msg
        # duplicate logging
        if _dup:
            _dup.log(level, line)
        # print to stderr
        _stream.write(_color_dict.get(level, b""))
        _stream.write(line)
        _stream.write(b"\033[0m\n")

    def debug(self, msg, *args):
        self.log(DEBUG, msg, *args)

    def info(self, msg, *args):
        self.log(INFO, msg, *args)

    def warning(self, msg, *args):
        self.log(WARNING, msg, *args)

    def error(self, msg, *args):
        self.log(ERROR, msg, *args)

    def critical(self, msg, *args):
        self.log(CRITICAL, msg, *args)

    def exc(self, e, msg, *args):
        self.log(ERROR, msg, *args)
        sys.print_exception(e, self)

    def exception(self, msg, *args):
        self.exc(sys.exc_info()[1], msg, *args)

    # write is only to be used by sys.print_exception
    def write(self, buf):
        if buf == b"":
            return
        lines = (self.wbuf + buf).split(b"\n")
        self.wbuf = lines[-1]
        for l in lines[:-1]:
            self.log(ERROR, l)


_level = INFO
_loggers = {}


def getLogger(name):
    if name in _loggers:
        return _loggers[name]
    l = Logger(name)
    _loggers[name] = l
    return l


def info(msg, *args):
    getLogger(None).info(msg, *args)


def debug(msg, *args):
    getLogger(None).debug(msg, *args)


def basicConfig(level=INFO, filename=None, stream=None, format=None):
    global _level, _stream
    _level = level
    if stream:
        _stream = stream
    if filename is not None:
        print("filename arg is not supported")
    if format is not None:
        print("format arg is not supported")


MAX_LINE = const(256)  # max line length sent by MQTT logger


class MQTTLog:
    def __init__(self, minlevel=ERROR, maxsize=2800):
        global _dup
        self._minlevel = minlevel
        self._qmax = maxsize
        self._q = []
        self._qlen = 0
        self._ev = Event()
        _dup = self

    def resize(self, maxsize):
        self._qmax = maxsize
        # first try to eliminate messages below warning
        i = 0
        while self._qlen > maxsize and i < len(self._q):
            if self._q[i][0] < WARNING:
                self._qlen -= len(self._q[i][1])
                del self._q[i]
            i += 1
        # if not there yet, eliminate other messages too
        while self._qlen > maxsize:
            self._qlen -= len(self._q[0])
            del self._q[0]

    def log(self, level, msg):
        if level < self._minlevel:
            return
        if len(msg) > MAX_LINE:
            msg = msg[:MAX_LINE]
        ll = len(msg)
        self.resize(self._qmax)
        self._q.append((level, msg))
        self._qlen += ll
        self._ev.set()

    async def run(self, mqclient, topic):
        print("MQTTLog:", topic)
        while True:
            while len(self._q) > 0:
                msg = self._q[0][1]
                try:
                    await mqclient.publish(topic, msg, qos=1, sync=False)
                except Exception as e:
                    print("Exception", e)
                    await sleep_ms(1000)
                self._qlen -= len(msg)
                del self._q[0]
            self._ev.clear()
            await self._ev.wait()


def start(mqtt, config):
    try:
        from __main__ import mqtt_logger

        mqtt_logger.resize(config.get("loop_sz", 1400))
        mqtt_logger.level = config.get("loop_level", WARNING)
        #
        get_event_loop().create_task(mqtt_logger.run(mqtt.client, config["topic"]))
    except Exception as e:
        print("MQTTLog failed to start")
        sys.print_exception(e)
