# logging with MQTT support
# This is a modified version of the micropython-lib logging module with the addition
# of being able to log to MQTT.

import sys, io


try:
    from time import ticks_ms, ticks_diff, ticks_add, time, localtime
    from uasyncio import Event, sleep_ms, Loop as loop
except Exception:
    from time import monotonic, time

    def ticks_ms():
        return monotonic() * 1000

    def ticks_diff(a, b):
        return a - b

    def ticks_add(a, b):
        return a + b

    def const(c):
        return c

    from asyncio import Event, get_event_loop, sleep

    loop = get_event_loop()

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

_hour_ticks = None  # ticks_ms value at top of last hour
_hour = None
TICKS_PER_HOUR = const(3600 * 1000)
TIME_2020 = const(631180800)  # time.mktime((2020,1,1,0,0,0,0,0,0))


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

    # calculate time-of-day from ticks_ms by using offset to the last top of the hour
    @staticmethod
    def _time_str(t):
        global _hour_ticks, _hour
        if _hour_ticks is None or ticks_diff(t, _hour_ticks) > TICKS_PER_HOUR:
            tm = time()
            if tm < TIME_2020:  # we don't know the time
                return str(t)
            tm = localtime(tm)
            _hour = tm[3]
            _hour_ticks = ticks_add(t, -(((tm[4] * 60) + tm[5]) * 1000))
        dt = ticks_diff(t, _hour_ticks)
        return "%02d:%02d:%02d.%03d" % (
            _hour,
            (dt // 60000) % 60,  # minutes
            (dt // 1000) % 60,  # seconds
            dt % 1000,  # millis
        )

    def log(self, level, msg, *args):
        t = ticks_ms() % 100000000
        if level < (self.level or _level):
            return
        # prep full text
        line = "%s %s %8s: " % (self._level_str(level), Logger._time_str(t), self.name)
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


MAX_LINE = const(1024)  # max line length sent by MQTT logger


# MQTTLog logs via MQTT; do not instantiate directly, use MQTTLog function
class MQTTLog:
    _minlevel = ERROR
    _qmax = 1400
    _q = []
    _qlen = 0
    _ev = Event()

    @classmethod
    def init(cls, minlevel=ERROR, maxsize=1400):
        global _dup
        _dup = cls
        cls._minlevel = minlevel
        cls.resize(maxsize)

    @classmethod
    def resize(cls, maxsize):
        cls._qmax = maxsize
        # first try to eliminate messages below warning level
        i = 0
        while cls._qlen > maxsize and i < len(cls._q):
            if cls._q[i][0] < WARNING:
                cls._qlen -= len(cls._q[i][1])
                del cls._q[i]
            i += 1
        # if not there yet, eliminate other messages too
        while cls._qlen > maxsize:
            cls._qlen -= len(cls._q[0][1])
            del cls._q[0]

    @classmethod
    def log(cls, level, msg):
        if level < cls._minlevel:
            return
        if len(msg) > MAX_LINE:
            msg = msg[:MAX_LINE]
        ll = len(msg)
        cls._q.append((level, msg))
        cls._qlen += ll
        if cls._qlen > cls._qmax:
            cls.resize(cls._qmax)
        cls._ev.set()

    @classmethod
    async def push(cls, mqclient, topic):
        msg = cls._q[0][1]
        try:
            await mqclient.publish(topic, msg, qos=1, sync=False)
        except Exception as e:
            print("Exception", e)
            await sleep_ms(1000)
        cls._qlen -= len(msg)
        del cls._q[0]

    @classmethod
    async def run(cls, mqclient, topic):
        while True:
            while len(cls._q) > 0:
                await cls.push(mqclient, topic)
            cls._ev.clear()
            await cls._ev.wait()

    # connected is called when the first bropker connection is established, it flushes excess
    # saved messages while blocking further inits by other modules, then resizes the log storage,
    # and starts the regular runner/flusher
    @classmethod
    async def connected(cls, mqtt, config):
        topic = config["topic"]
        getLogger("main").info("Logging to %s", topic)
        # flush what we'd need cut due to resize
        maxsize = config.get("loop_sz", 1400)
        getLogger("main").info("Log buf: %d/%d bytes", cls._qlen, cls._qmax)
        while cls._qlen > maxsize*3//4:
            await cls.push(mqtt.client, topic)
        # re-init including resize
        MQTTLog.init(
            minlevel=config.get("loop_level", WARNING), maxsize=maxsize,
        )
        getLogger("main").info("Log buf: %d/%d bytes", cls._qlen, cls._qmax)
        # launch regular flusher
        loop.create_task(MQTTLog.run(mqtt.client, topic))


# start is called when the module is loaded, just save the config and register on_init CB
def start(mqtt, config):
    mqtt.on_init(MQTTLog.connected(mqtt, config))
