# Watchdog task to keep feeding the watchdog timer via MQRepl
# Copyright © 2020 by Thorsten von Eicken.
import sys, machine, logging, time, struct, uasyncio as asyncio


MAGIC1 = 0xF00D
MAGIC2 = 0xBEEF
CMD = "cmd/eval/0F00D/"
# MSG = b"\x80\x00import watchdog; watchdog.wdt.feed()"
MSG = b"\x80\x00watchdog.feed()"
log = logging.getLogger(__name__)
first = 0  # time of first feeding

# feed is run by the loop-back message to feed the watchdog
def feed():
    global first
    wdt.feed()
    if safemode and not revert:
        return
    elif first is None:
        return  # done with safe mode stuff
    elif first == 0:
        first = time.ticks_ms()  # record time of first feeding
    elif time.ticks_diff(time.ticks_ms(), first) > allok:
        if sys.platform == 'esp32':
            # mark the current partition as OK, this prevents rollback after OTA
            from esp32 import Partition
            part = Partition(Partition.RUNNING)
            part.mark_app_valid_cancel_rollback()
        if safemode:
            log.critical("Switching to NORMAL MODE via reset")
            reset(True)
        else:
            log.warning("Next reset: normal boot")
            normalboot(True)
            first = None


# feeder is a task that periodically sends a loopback MQTT message to feed the watchdog
async def feeder(mqclient, topic):
    global timeout
    while True:
        try:  # TODO: an exception may be a good reason to stop!?
            log.info(topic)
            await mqclient.publish(topic, MSG, qos=1)
            await asyncio.sleep(timeout / 4)
        except Exception as e:
            log.exc(e, "In feeder:")


# normalboot sets the RTC memory to cause the next boot to be normal or safemode
def normalboot(normal):
    rtc = machine.RTC()
    mem = bytearray(rtc.memory())
    if len(mem) < 4:
        mem = bytearray(4)
    if normal:
        struct.pack_into("HH", mem, 0, MAGIC1, MAGIC2)
    else:
        struct.pack_into("HH", mem, 0, 0, 0)
    rtc.memory(mem)


# reset performs a delayed reset to allow logging time to send a farewell
def reset(mode):
    normalboot(mode == "n" or mode == "s")

    async def zap():
        await asyncio.sleep_ms(1000)
        if mode == "s":
            machine.soft_reset()
        else:
            machine.reset()

    asyncio.Loop.create_task(zap())


async def init(mqclient, prefix):
    asyncio.Loop.create_task(feeder(mqclient, prefix + CMD))


def start(mqtt, config):
    global wdt, timeout, safemode, revert, allok
    # Re-init WDT with configured timeout
    timeout = config.get("timeout", 300)
    wdt = machine.WDT(timeout=timeout * 1000)
    log.info("WDT updated with %d seconds timeout", timeout)
    # Init feeder config
    import __main__
    safemode = __main__.safemode
    revert = config.get("revert", True)
    allok = config.get("allok", 300) * 1000
    __main__.GLOBALS()["watchdog"] = sys.modules["watchdog"]
    # Feeder starts once we're connected
    mqtt.on_init(init(mqtt.client, config["prefix"]))
