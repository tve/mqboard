#! /bin/bash -e
export PYBOARD_DEVICE=${PYBOARD_DEVICE:-/dev/ttyUSB0}
export PATH=$HOME/bin:$PATH

echo "----- flashing MicroPython -----"
src=$HOME/save/mp/tve/esp32/firmware.bin
$HOME/esp-idf-v4/components/esptool_py/esptool/esptool.py --chip esp32 --port $PYBOARD_DEVICE \
    --baud 460800 write_flash -z --flash_mode dio --flash_freq 40m 0x1000 $src |& \
    sed -e '/Writing at 0x/d'
[[ $? == 0 ]] || exit 1
sleep 3 # time for the board to boot

echo "---- checking that the board came up ----"
pyboard.py -c "print('hello world')"

echo 'SUCCESS!'
