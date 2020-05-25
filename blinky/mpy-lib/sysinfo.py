import micropython, gc, time, uasyncio as asyncio, logging

log = logging.getLogger(__name__)

_upticks = None  # milliseconds of uptime (becomes a bigint unlike time_ms())
_lastticks = None  # helper to keep track of _upticks
_mqttconn = 0  # number of MQTT connections


# info_sender is a task (must be launched using create_task) that sends an MQTT info message
# every interval seconds to the specified topic.
async def info_sender(mqclient, topic, interval):
    global _upticks, _lastticks
    log.info(topic)
    while True:
        try:
            gc.collect()
            f = gc.mem_free()
            mf = gc.mem_maxfree()
            t = time.ticks_ms()
            if _upticks is None:
                _upticks = t  # we hope it hasn't rolled-over yet...
            else:
                _upticks += time.ticks_diff(t, _lastticks)
            _lastticks = t
            # compose json message with data
            msg = '{"up":%d,"free":%d,"cont_free":%d,"mqtt_conn":%d}' % (
                _upticks // 1000,
                f,
                mf,
                _mqttconn,
            )
            log.info(msg)
            await mqclient.publish(topic, msg, qos=0)
            # micropython.mem_info()
        except Exception as e:
            log.exc(e, "Exception")
        await asyncio.sleep(interval)


async def _on_mqtt(conn):
    global _mqttconn
    if conn:
        _mqttconn += 1


async def _on_init(mqclient, topic, interval):
    asyncio.sleep(1)  # skip initial flurry of activity
    asyncio.get_event_loop().create_task(info_sender(mqclient, topic, interval))


def start(mqtt, config):
    mqtt.on_init(_on_init(mqtt.client, config["topic"], config.get("interval", 60)))
    mqtt.on_mqtt(_on_mqtt)
