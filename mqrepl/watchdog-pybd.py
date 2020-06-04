# Watchdog task to keep feeding the watchdog timer via MQRepl -- PYBD version
# Copyright © 2020 by Thorsten von Eicken.
import sys, machine, logging, time, struct, uasyncio as asyncio


MAGIC1 = 0xF00D
MAGIC2 = 0xBEEF
CMD = "cmd/eval/0F00D/"
# MSG = b"\x80\x00import watchdog; watchdog.wdt.feed()"
MSG = b"\x80\x00watchdog.feed()"
log = logging.getLogger(__name__)
first = 0  # time of first feeding

feeding = 0  # last feeding (as ticks_ms)
timeout = 30000  # timeout in milliseconds


def _feed_task():
    global feeding
    feeding = time.ticks_ms()
    wdt = machine.WDT(0, 5000)
    while True:
        if time.ticks_diff(time.ticks_ms(), feeding) < timeout:
            wdt.feed()
        await asyncio.sleep(1)


# feed is run by the loop-back message to feed the watchdog
def feed():
    global first, feeding
    feeding = time.ticks_ms()
    if safemode and not revert:
        return
    elif first is None:
        return  # done with safe mode stuff
    elif first == 0:
        first = time.ticks_ms()  # record time of first feeding
    elif time.ticks_diff(time.ticks_ms(), first) > allok:
        if safemode:
            log.critical("Switching to NORMAL MODE via reset")
            reset(True)


# feeder is a task that periodically sends a loopback MQTT message to feed the watchdog
async def feeder(mqclient, topic):
    global timeout
    while True:
        try:  # TODO: an exception may be a good reason to stop!?
            log.info(topic)
            await mqclient.publish(topic, MSG, qos=1)
            await asyncio.sleep_ms(timeout // 4)
        except Exception as e:
            log.exc(e, "In feeder:")


def _wdt_reset():
    machine.WDT(0, 2)


async def _reset(f):
    print("_reset")
    await asyncio.sleep_ms(400)
    f()


# reset performs a delayed reset to allow logging time to send a farewell
def reset(mode):
    f = {"n": machine.reset, "f": _wdt_reset, "s": machine.soft_reset}[mode]
    asyncio.Loop.create_task(_reset(f))


async def init(mqclient, prefix):
    asyncio.Loop.create_task(feeder(mqclient, prefix + CMD))


def start(mqtt, config):
    log.info("PYBD Watchdog")
    global wdt, timeout, safemode, revert, allok
    # Re-init WDT with configured timeout
    timeout = config.get("timeout", 300) * 1000
    log.info("WDT updated with %d seconds timeout", timeout)
    asyncio.Loop.create_task(_feed_task())
    # Init feeder config
    import __main__

    safemode = __main__.safemode
    revert = config.get("revert", True)
    allok = config.get("allok", 300) * 1000
    __main__.GLOBALS()["watchdog"] = sys.modules["watchdog"]
    # Feeder starts once we're connected
    mqtt.on_init(init(mqtt.client, config["prefix"]))
