# Copyright © 2020 by Thorsten von Eicken.
import mqrepl, logging
import uasyncio as asyncio

logging.basicConfig(level=logging.INFO)

# MQTT is a stub for mqtt.MQTT
class MQTT:
    def __init__(self, mqclient):
        self.client = mqclient
        self.init_cb = None
        self.msg_cb = None

    def on_init(self, cb):
        self.init_cb = cb
        asyncio.Loop.create_task(cb)

    def on_msg(self, cb):
        print("MQTT.on_msg(%s) called" % str(cb))
        self.msg_cb = cb


# MQTTCli is a stub for mqtt_async.MQTTClient
class MQTTCli:
    def __init__(self):
        self.sub = None
        self.pub = None

    async def subscribe(self, topic, qos=-1):
        self.sub = (topic, qos)

    async def publish(self, topic, msg, retain=False, qos=-1):
        self.pub = (topic, msg, retain, qos)

# test_start_stop tests the start() and stop() methods of MQRepl
async def test_start_stop():
    mqclient = MQTTCli()
    mqtt = MQTT(mqclient)
    mqrepl.start(mqtt, {"prefix":"esp32/test/mqb/"})
    await asyncio.sleep_ms(20)
    #
    assert isinstance(mqclient.sub, tuple)
    assert mqclient.sub[1] == 1  # check QoS
    assert mqtt.init_cb, "MQTT.on_init was not called"
    assert mqtt.msg_cb, "MQTT.on_msg was not called"
    #mqr.stop()
    print("start-stop OK")


# test_eval_cmd tests a simple `eval` command to see that the plumbing works
async def test_eval_cmd():
    print("== starting mqrepl")
    mqclient = MQTTCli()
    mqtt = MQTT(mqclient)
    mqrepl.start(mqtt, {"prefix":"foo/"})
    await asyncio.sleep_ms(20)
    print("== checking subscription and callbacks")
    assert isinstance(mqclient.sub, tuple)
    assert mqclient.sub[0] == "foo/cmd/#", "mqclient.sub[0] is: "+str(mqclient.sub[0])
    assert mqclient.sub[1] == 1  # check QoS
    assert mqtt.init_cb
    assert mqtt.msg_cb
    print("== sending command")
    topic = b"foo/cmd/eval/99cF00D/"
    print("publishing to", topic)
    mqtt.msg_cb(topic, b"\x80\x001+3", False, 1, 0)
    await asyncio.sleep_ms(50)
    if mqclient.pub and mqclient.pub[1] == b"\xff\xff4" and mqclient.pub[3] == 1:
        print("eval command OK")
    else:
        print("eval FAILED:", mqclient.pub)


print("===== test start-stop =====")
asyncio.run(test_start_stop())
print("\n===== test eval =====")
asyncio.run(test_eval_cmd())
