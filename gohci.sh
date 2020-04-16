#! /bin/bash -e
PORT=/dev/ttyUSB0
export PATH=$HOME/bin:$PATH

echo "----- flashing MicroPython -----"
src=$HOME/save/mp/tve/esp32/firmware.bin
./esp-idf-v4/components/esptool_py/esptool/esptool.py --chip esp32 --port $PORT --baud 460800 \
    write_flash -z --flash_mode dio --flash_freq 40m 0x1000 $src
