#! /bin/bash -e
PORT=/dev/ttyUSB0
export PATH=$HOME/bin:$PATH
cd $(dirname $0)
pwd

echo "---- checking pyboard serial ----"
pyboard.py --device $PORT -c "print('hello world')" || true

echo "----- uploading board files -----"
pyboard.py --device $PORT -f cp board.py boot.py logging.py main.py :
pyboard.py --device $PORT -f cp $HOME/board_config_esp32.py :board_config.py
out=$(pyboard.py --device $PORT -f ls)
if [ "$out" != *board.py*board_config.py*boot.py*logging.py*main.py* ]; then
	echo OOPS, got: "$out"
	exit 1
fi

echo "----- resetting and connecting to wifi -----"
python3 -c "import serial; s=serial.serial_for_url('$PORT'); s.setDTR(0); s.setDTR(1)"
sleep 3
out=$(timeout 1m pyboard.py --device $PORT -c 'connect_wifi()')
echo "$out" | egrep 'Connected'

echo "----- check that board variables are set -----"
out=$(pyboard.py --device $PORT -c "from board import *; print(kind, led, bat_volt_pin, bat_fct)")
if ! [ "$out" == "a b c" ]; then
	echo OOPS, got: "$out"
	exit 1
fi
