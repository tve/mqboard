# This file is executed on every boot (including wake-boot from deepsleep)

import sys
sys.path.append('/src')

from esp32 import Partition as p
print("Booting partition", p(p.RUNNING).info()[4])

import board

# connect_wifi is a handy little function to manually connect wifi
def connect_wifi():
    import network
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    print('Connecting to', board.wifi_ssid, '...')
    wlan.connect(board.wifi_ssid, board.wifi_pass)
    while not wlan.isconnected():
        pass
    print('Connected!')
