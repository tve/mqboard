# This file is executed on every boot (including wake-boot from deepsleep)

import sys
sys.path.append('/src')

import board

#import webrepl
#webrepl.start()

def connect_wifi():
    import network
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    print('Connecting to', board.wifi_ssid, '...')
    wlan.connect(board.wifi_ssid, board.wifi_pass)
    while not wlan.isconnected():
        pass
    print('Connected!')
