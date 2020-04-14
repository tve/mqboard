#! /bin/bash -e
PORT=/dev/ttyUSB0
export PATH=$HOME/bin:$PATH
cd $(dirname $0)
pwd

echo "----- pytest test_client.py in CPython -----"
pytest

echo "---- checking pyboard serial ----"
pyboard.py --device $PORT -c "print('hello world')" || true

echo "----- pyboard test_proto on esp32 -----"
pyboard.py --device $PORT -f cp mqtt_async.py ../board/logging.py :
pyboard.py --device $PORT -c connect_wifi()
sleep 1
pyboard.py --device $PORT test_proto.py
pyboard.py --device $PORT -f rm :mqtt_async.py
