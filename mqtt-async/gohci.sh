#! /bin/bash -ex
PORT=/dev/ttyUSB0
export PATH=$HOME/bin:$PATH
cd $(dirname $0)
pwd

echo "----- pytest test_client.py in CPython -----"
pytest

echo "---- checking pyboard serial ----"
pyboard.py --device $PORT -c "print('hello world')" || true

echo "----- run test_proto on esp32 -----"
pyboard.py --device $PORT -f cp mqtt_async.py :
pyboard.py --device $PORT -c 'connect_wifi()'
sleep 1
pyboard.py --device $PORT test_proto.py

echo "----- run test_proto on esp32 -----"
pyboard.py --device $PORT test-bench.py

echo "----- clean-up -----"
pyboard.py --device $PORT -f rm :mqtt_async.py
