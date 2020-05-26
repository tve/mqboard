#! /bin/bash -e
DIR=$(dirname $0)
echo device: ${PYBOARD_DEVICE:-/dev/ttyACM0}

pyboard.py -f cp $DIR/board/boot.py :
[[ "$(pyboard.py -f ls)" == *safemode* ]] || pyboard.py -f mkdir /safemode
pyboard.py -f cp \
    $DIR/board/{main,board,logging,mqtt}.py \
    $DIR/mqrepl/{mqrepl,watchdog}.py \
    $DIR/mqtt_async/mqtt_async.py \
    :/safemode/

if [[ "$(pyboard.py -f ls)" != *board_config.py* ]]; then
    if [[ -f $DIR/board/board_config.py ]]; then
        pyboard.py -f cp $DIR/board/board_config.py :/safemode/
    else
        echo "Please load board_config.py manually"
    fi
else
    echo "board_config.py left as-is"
fi
