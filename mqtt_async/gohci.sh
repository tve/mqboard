#! /bin/bash -ex
export PYBOARD_DEVICE=${PYBOARD_DEVICE:-/dev/ttyUSB0}
export PATH=$HOME/bin:$PATH
cd $(dirname $0)
pwd

echo "----- pytest test_client.py in CPython -----"
pytest

echo "---- checking pyboard serial ----"
pyboard.py -c "print('hello world')" || true

echo "----- run test_proto on esp32 -----"
pyboard.py -f cp mqtt_async.py :/safemode/
pyboard.py -c 'connect_wifi()'
sleep 1
timeout 1m pyboard.py test_proto.py

#echo "----- run test_bench on esp32 -----"
#timeout 1m pyboard.py test-bench.py

echo 'SUCCESS!'
