#! /bin/bash -e
DIR=$(dirname $0)
echo device: ${PYBOARD_DEVICE:-/dev/ttyACM0}
pyboard -f cp $DIR/board/{board,boot,logging,main}.py $DIR/mqrepl/mqrepl.py $DIR/mqtt_async/mqtt_async.py :

