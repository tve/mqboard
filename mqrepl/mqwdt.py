import machine, logging, time, uasyncio as asyncio

log = logging.getLogger(__name__)

topic = b"cmd/exec/0F00D/"
msg = b'\x80\x00import mqwdt; mqwdt.wdt.feed()'


async def feeder(mqclient):
    global timeout
    while True:
        try:
            log.info(topic)
            await mqclient.publish(topic, msg, qos=1)
            await asyncio.sleep(timeout / 4)
        except Exception as e:
            log.warning("%s in wdt task", e)


async def connected(mqclient):
    log.info(topic)
    await mqclient.publish(topic, msg, qos=1)


def start(mqtt):
    global topic
    import mqrepl
    topic = mqrepl.TOPIC + topic
    asyncio.Loop.create_task(feeder(mqtt.client))
    mqtt.on_connect(connected)


def init(timeout_secs):
    global timeout, wdt
    timeout = timeout_secs
    wdt = machine.WDT(timeout=timeout_secs * 1000)
    log.info("WDT started with %d seconds timeout", timeout)
