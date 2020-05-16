import logging, time, struct, uasyncio as asyncio
from machine import RTC

conn = asyncio.Event()
log = logging.getLogger(__name__)
log.setLevel(logging.DEBUG)
rtc = RTC()


async def safe_conn(cli):
    global conn
    conn.set()


async def safe_loop(mqtt):
    await conn.wait()
    await asyncio.sleep(300)  # safe mode delay


# safe_ok flags that a coming reboot should not enter safe mode
def safe_ok():
    rtc.memory(struct.pack("Ii", 0xFEEDF00D, time.time() - 301))


def start(mqtt, config=None):

    # try to get the time of the previous boot
    time.sleep_ms(20)
    rtc_mem = rtc.memory()
    if len(rtc_mem) >= 8:
        (f00d, last_boot) = struct.unpack_from("Ii", rtc_mem, 0)
        if f00d != 0xFEEDF00D:
            last_boot = None  # prevent safe mode
            log.debug("RTC memory was corrupted")
    else:
        log.debug("RTC memory was cleared")
        last_boot = None
    del rtc_mem

    # update RTC boot time
    # FIXME: if this is a cold boot and this_boot==0 we could update again later when the time
    # gets set correctly, the way it's now it will take two crashes to enter safe mode
    this_boot = time.time()
    rtc.memory(struct.pack("Ii", 0xFEEDF00D, this_boot))

    # if the time is not set there was a hard reset or power cycle: no need for safe mode
    # if the system was up for more than 5 minutes: no need for safe mode
    log.info("Time=%d, Last boot=%s", this_boot, last_boot)
    if last_boot is not None and this_boot - last_boot < 300:
        # enter safe mode
        mqtt.on_connect(safe_conn)
        log.warning("-- Starting SAFE MODE loop")
        asyncio.run(safe_loop(mqtt))
        log.warning("-- Leaving SAFE MODE")
