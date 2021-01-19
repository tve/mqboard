# mqtt - module to manage the MQTT client, specifically, to allow callback registrations
# regardless of starting order and to support a list of message callbacks
# Copyright © 2020 by Thorsten von Eicken.

from uasyncio import sleep_ms, Loop as loop
from board import act_led, fail_led
import logging

log = logging.getLogger(__name__)
# log.setLevel(logging.DEBUG)


class MQTT:

    client = None  # will be mqtt_async.MQTTClient() instance

    _mqtt_cb = []  # list of callbacks for on_wifi (which is mis-named)
    _init_cb = []  # list of callbacks for on_connect (which is mis-named)
    _msg_cb = []  # list of callbacks for on_msg

    # on_mqtt registers a callback coro to be launched when a connection to the MQTT broker
    # is established or torn down. It's useful to blink LEDs or to gate activity based on
    # the connection status.
    # The callbacks are made using create_task and are passed a `is_connected` True/False
    # argument.
    # Tip: given `async def my_cb(connected)` use `on_mqtt(my_cb)`.
    @classmethod
    def on_mqtt(cls, cb):
        cls._mqtt_cb.append(cb)

    @classmethod
    async def _mqtt_handler(cls, connected):
        fail_led(not connected)
        if connected:
            log.info("MQTT connected (->%d)", len(cls._mqtt_cb))
        else:
            log.info("MQTT disconnected (->%d)", len(cls._mqtt_cb))
        for cb in cls._mqtt_cb:
            loop.create_task(cb(connected))

    # on_init registers a callback awaitable to be awaited when the first connection to the broker
    # is made.
    # It is useful to trigger subscriptions and to generally delay starting activity until
    # there's a connection, which keeps more memory free to buffer boot logs until the connection
    # is made.
    # The callbacks are made using await and are processed in the order they are registered,
    # which is the order of the board.modules list. This allows modules, such as logging, to
    # push messages out in their callback while stalling the init process so memory usage is
    # kept under control.
    # Tip: given `async def my_cb(some, args)` use `on_init(my_cb(current, values))`.
    @classmethod
    def on_init(cls, cb):
        cls._init_cb.append(cb)

    @classmethod
    async def _init_handler(cls, mqclient):
        log.info("Initial MQTT connection (->%d)", len(cls._init_cb))
        for cb in cls._init_cb:
            await cb

    # on_msg registers a callback function to be called when a message arrives on a subscription.
    # The callbacks are direct function calls and must not block. They are passed topic, payload,
    # retained_flag, qos level, and dup flag. The message is not acked until all the callbacks
    # complete.
    # Tip: given `def my_cb(topic, msg, retained, qos, dup)` use `on_msg(my_cb)`.
    @classmethod
    def on_msg(cls, cb):
        cls._msg_cb.append(cb)

    @classmethod
    def _msg_handler(cls, topic, msg, retained, qos, dup):
        log.debug("RX %s (->%d): %s", topic, len(cls._msg_cb), msg)
        loop.create_task(cls._pulse_act())
        for cb in cls._msg_cb:
            cb(topic, msg, retained, qos, dup)

    # pulse activity LED (typ. blue)
    async def _pulse_act():
        act_led(True)
        await sleep_ms(100)
        act_led(False)


def start(cls, config):
    from mqtt_async import MQTTClient

    # set the dhcp hostname so this esp32 can be identified when looking at the router/dhc server
    # this is a hack for now, what should probably be done is to pull wifi_connect out of mqtt_async
    # and put that somewhere it can be customized easily.
    hn = config.get("dhcp_hostname") or config.get("user") or config.get("client_id")
    if hn:
        from network import WLAN, STA_IF
        import ure as re
        wlan = WLAN(STA_IF)
        wlan.active(True)
        hn = re.sub("[^a-zA-Z0-9]", "-", hn)
        log.info("Setting dhcp hostname to %s", hn)
        wlan.config(dhcp_hostname=hn)

    config["subs_cb"] = cls._msg_handler
    config["wifi_coro"] = cls._mqtt_handler
    config["connect_coro"] = cls._init_handler
    fail_led(True)
    cls.client = MQTTClient(config)
    cls.client.start()
