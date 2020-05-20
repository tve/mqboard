import logging, time, machine, struct, uasyncio as asyncio

log = logging.getLogger(__name__)

MIN_RUNTIME = const(300)  # minimum runtime req'd in previous life to enter regular mode
MAGIC1 = 0xF00D
MAGIC2 = 0xBEEF


async def safe_conn(cli):
    await asyncio.sleep(MIN_RUNTIME)  # safe mode delay
    force()


# force a coming reboot into safemode or into regular mode
def force(safe=False):
    magic = 0 if safe else MAGIC
    mem = bytearray(rtc.memory())
    if len(mem) < 4:
        mem = bytearray(4)
    struct.pack_into("I", mem, 0, magic)
    rtc.memory(mem)


def start(mqtt, config):
    from __main__ import safemode
    if safemode:

    mqtt.on_connect(safe_conn)
    loop.create_task(safe_loop(mqtt))
