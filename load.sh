#! /bin/bash -e
DIR=$(dirname $0)
echo device: ${PYBOARD_DEVICE:-/dev/ttyACM0}
pyboard -f cp $DIR/board/{board,boot,logging,main,mqtt}.py $DIR/mqrepl/{mqrepl,watchdog,safemode}.py $DIR/mqtt_async/mqtt_async.py :
if [[ "$(pyboard -f ls)" != *board_config.py* ]]; then
    echo "Please load board_config.py manually"
else
    echo "board_config.py left as-is"
fi
