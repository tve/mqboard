#! /bin/bash -e
PORT=/dev/ttyUSB0
export PATH=$HOME/bin:$PATH
cd $(dirname $0)
pwd

echo "---- checking pyboard serial ----"
pyboard.py --device $PORT -c "print('hello world')" || true

echo "---- wiping flash clean ----"
pyboard.py --device $PORT rm_rf.py

echo "----- uploading board files -----"
pyboard.py --device $PORT -f cp board.py boot.py logging.py main.py :
board_config=$HOME/board_config_esp32.py
[ -f $board_config ] || board_config=board_config.py # for local testing
pyboard.py --device $PORT -f cp $board_config :board_config.py
out=$(pyboard.py --device $PORT -f ls)
if [[ "$out" != *board.py*board_config.py*boot.py*logging.py*main.py* ]]; then
	echo OOPS, got: "$out"
	exit 1
fi

echo "----- resetting and connecting to wifi -----"
python3 -c "import serial; s=serial.serial_for_url('$PORT'); s.setDTR(0); s.setDTR(1)"
echo did reset
sleep 2
out=$(timeout 1m pyboard.py --device $PORT -c 'connect_wifi()' || true)
if [[ "$out" != *Connected* ]]; then
	echo OOPS, got: "$out"
	exit 1
fi

echo "----- check that board variables are set -----"
out=$(pyboard.py --device $PORT -c "from board import *; print(len(kind)>2, act_led!=False, fail_led!=False, bat_volt_pin, bat_fct)")
if [[ "$out" != *"True True True None 2"* ]]; then
	echo OOPS, got: "$out"
	exit 1
fi
echo 'Success!'
