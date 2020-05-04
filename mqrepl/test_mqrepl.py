import mqrepl, logging
import uasyncio as asyncio

logging.basicConfig(level=logging.INFO)

# MQTT is a stub for mqtt.MQTT
class MQTT:
    def __init__(self, mqclient):
        self.client = mqclient
        self.conn_cb = None
        self.msg_cb = None

    def on_connect(self, cb):
        self.conn_cb = cb

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
    mqr = mqrepl.MQRepl(mqtt)
    await mqr.start(mqclient)
    mqr.stop()
    assert isinstance(mqclient.sub, tuple)
    assert mqclient.sub[1] == 1  # check QoS
    assert mqtt.conn_cb
    assert mqtt.msg_cb
    print("start-stop OK")


# test_eval_cmd tests a simple `eval` command to see that the plumbing works
async def test_eval_cmd():
    print("== starting mqrepl")
    mqclient = MQTTCli()
    mqtt = MQTT(mqclient)
    mqr = mqrepl.MQRepl(mqtt, {"prefix":b"foo"})
    await mqr.start(mqclient)
    assert isinstance(mqclient.sub, tuple)
    assert mqclient.sub[0] == b"foo/mqb/cmd/#", "mqclient.sub[0] is: "+str(mqclient.sub[0])
    assert mqclient.sub[1] == 1  # check QoS
    assert mqtt.conn_cb
    assert mqtt.msg_cb
    print("== sending command")
    topic = b"foo/mqb/cmd/eval/99cF00D/"
    print("publishing to", topic)
    mqtt.msg_cb(topic, b"\x80\x001+3", False, 1)
    await asyncio.sleep_ms(50)
    if mqclient.pub and mqclient.pub[1] == b"\x80\x004" and mqclient.pub[3] == 1:
        print("eval command OK")
    else:
        print("eval FAILED:", mqclient.pub)


print("===== test start-stop =====")
asyncio.run(test_start_stop())
print("\n===== test eval =====")
asyncio.run(test_eval_cmd())
