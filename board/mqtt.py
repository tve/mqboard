# mqtt - module to hold the top-level references that make mqtt and mqrepl work so
# other modules can import mqtt and get access to things...

from uasyncio import sleep_ms, Loop as loop
from board import config, act_led, fail_led
import logging

log = logging.getLogger(__name__)
#log.setLevel(logging.DEBUG)


#def is_awaitable(f):
#    return f.__class__.__name__ == "generator"


class MQTT:

    client = None  # will be mqtt_async.MQTTClient() instance
    # repl = None  # will be mqrepl.MQRepl() instance

    _wifi_cb = []  # list of callbacks for on_wifi
    _connect_cb = []  # list of callbacks for on_connect
    _msg_cb = []  # list of callbacks for on_msg

    # on_wifi registers a callback coro to be called when wifi connects or disconnects.
    # The callbacks are made using create_task and are passed a `is_connected` True/False
    # argument.
    @classmethod
    def on_wifi(cls, cb):
        cls._wifi_cb.append(cb)

    @classmethod
    async def _wifi_handler(cls, connected):
        fail_led(not connected)
        if connected:
            log.info("Wifi connected (->%d)", len(cls._wifi_cb))
        else:
            log.info("Wifi disconnected (->%d)", len(cls._wifi_cb))
        for cb in cls._wifi_cb:
            loop.create_task(cb(connected))

    # on_connect registers a callback coro to be called when a connection to the broker is first made.
    # The callbacks are made using create_task and are passed a handle to the MQTTClient object.
    @classmethod
    def on_connect(cls, cb):
        cls._connect_cb.append(cb)

    @classmethod
    async def _connect_handler(cls, mqclient):
        log.info("MQTT connected (->%d)", len(cls._connect_cb))
        for cb in cls._connect_cb:
            loop.create_task(cb(mqclient))

    # on_msg registers a callback function to be called when a message arrives on a subscription.
    # The callbacks are direct function calls and must not block. They are passed topic, payload,
    # retained_flag, and qos level.
    @classmethod
    def on_msg(cls, cb):
        cls._msg_cb.append(cb)

    # pulse blue LED
    async def _pulse_act():
        act_led(True)
        await sleep_ms(100)
        act_led(False)

    @classmethod
    def _msg_handler(cls, topic, msg, retained, qos, dup):
        log.debug("RX %s (->%d): %s", topic, len(cls._msg_cb), msg)
        loop.create_task(cls._pulse_act())
        for cb in cls._msg_cb:
            cb(topic, msg, retained, qos, dup)

def start(cls, conf={}):
    from mqtt_async import MQTTClient
    config["subs_cb"] = cls._msg_handler
    config["wifi_coro"] = cls._wifi_handler
    config["connect_coro"] = cls._connect_handler
    config["clean"] = conf.get("clean", False)
    fail_led(True)
    cls.client = MQTTClient(config)
    cls.client.start()
