#! /bin/bash
PORT=/dev/ttyUSB0
export PATH=$HOME/bin:$PATH
cd $(dirname $0)
pwd

cat <<'EOF' >/tmp/foo
from mqtt_async import MQTTClient, config
import mqrepl, logging, board
import uasyncio as asyncio
CMD_ID = 'F00D'
config["port"] = 1883
config["ssl_params"] = None

async def test_start_stop():
    mqr = mqrepl.MQRepl()
    await mqr.start(config)
    await mqr.stop()
    print("start-stop OK")

got = None
async def subs(topic, msg, retained, qos):
    print("Got:", topic, msg)
    global got
    got = msg

async def test_ls_cmd():
    print("== starting mqrepl")
    mqr = mqrepl.MQRepl()
    await mqr.start(config)
    await asyncio.sleep_ms(100)
    print("== starting client")
    conf = config.copy()
    conf["clean"] = True
    conf["subs_cb"] = subs
    conf["connect_coro"] = None
    conf["wifi_coro"] = None
    conf["client_id"] += "-cmd"
    mqc = MQTTClient(conf)
    await mqc.connect()
    print("subscribing to", mqrepl.TOPIC+"reply/out/"+CMD_ID)
    await mqc.subscribe(mqrepl.TOPIC+"reply/out/"+CMD_ID, 1)
    print("publishing to", mqrepl.TOPIC+"cmd/eval/"+CMD_ID+"/")
    await mqc.publish(mqrepl.TOPIC+"cmd/eval/"+CMD_ID+"/", b"\x80\x001+3", qos=1)
    await asyncio.sleep_ms(1000)
    if got is None: await asyncio.sleep_ms(1000)
    if got == b"\x80\x004":
        print("eval command OK")
    else:
        print("eval FAILED:", got)

logging.basicConfig(level=logging.INFO)
ll=logging;ll._level_dict={ll.CRITICAL:"C",ll.ERROR:"E",ll.WARNING:"W",ll.INFO:"I",ll.DEBUG:"D"}
print("===== test start-stop =====")
asyncio.run(test_start_stop())
print("===== test ls =====")
asyncio.run(test_ls_cmd())

EOF

echo "---- checking pyboard serial ----"
pyboard.py --device $PORT -c "print('hello world')" || true

echo "---- installing files ----"
pyboard.py --device $PORT -f cp mqrepl.py ../mqtt-async/mqtt_async.py :

echo "---- running test ----"
#cat /tmp/foo
out=$(pyboard.py --device $PORT /tmp/foo)
#echo "$out"
if [[ "$out" != *"start-stop OK"*"eval command OK"* ]]; then
	echo OOPS, got: "$out"
	exit 1
fi
echo 'Success!'
