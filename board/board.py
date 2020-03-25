# Board configuration so other modules don't need to be too board-specific
import machine

# board_config needs to define:
# - kind: board type name, like huzzah32, lolin-d32, ...
# - location: short location name used in mqtt topics
# - wifi_ssid: SSID to connect to
# - wifi_pass: password
# - mqtt_server: IP address or hostname
# typically board_config.py is neither checked into version control nor published
from board_config import *

# ===== LED stuff and battery voltage stuff
# Defines `led(on_off)` and `get_battery_voltage()`

led = False
bat_volt_pin = None
bat_fct = 2 # voltage divider factor

if kind == "tve-bare":
    # bare esp32-wroom module with LED across IO23 and gnd
    lpin = machine.Pin(23, machine.Pin.OUT, None, value=1)
    led = lambda v: lpin(v)
    #machine.Pin(25, machine.Pin.OUT, None, value=1)
    #machine.Pin(27, machine.Pin.OUT, None, value=1)
elif kind == "huzzah32":
    # Adafruit Huzzah32 feather
    lpin = machine.Pin(13, machine.Pin.OUT, None, value=1)
    led = lambda v: lpin(v)
    #machine.Pin(25, machine.Pin.OUT, None, value=1)
    #machine.Pin(27, machine.Pin.OUT, None, value=1)
elif kind == "lolin-d32":
    lpin = machine.Pin(5, machine.Pin.OUT, None, value=1)
    led = lambda v: lpin(not v)
    bat_volt_pin = machine.ADC(machine.Pin(35))
    bat_volt_pin.atten(machine.ADC.ATTN_11DB)

def get_battery_voltage():
    """
    Returns the current battery voltage. If no battery is connected, returns 3.7V
    This is an approximation only, but useful to detect if the battery is getting low.
    """
    if bat_volt_pin == None:
        return 0
    measuredvbat = bat_volt_pin.read() / 4095
    measuredvbat *= 3.6*bat_fct # 3.6V at full scale
    return measuredvbat

# ===== MQTT stuff
# defines config stuff for mqtt_as

from mqtt_async import config
config.server = mqtt_server
config.ssid = wifi_ssid
config.wifi_pw = wifi_pass
config.listen_interval = 3

# For demos ensure the same calling convention for LED's on all platforms.
# ESP8266 Feather Huzzah reference board has active low LED's on pins 0 and 2.
# ESP32 is assumed to have user supplied active low LED's on same pins.
# Call with blue_led(True) to light

# TinyPICO has an RGB LED so we use the red channel for WiFi and the blue
# channel for message rx
if kind == 'tinypico':
    from led import dotstar
    color = [255, 0, 0]
    def set_red(v):
        color[0] = 255 if v else 0
        dotstar[0] = color
    def set_blue(v):
        color[2] = 255 if v else 0
        dotstar[0] = color
    wifi_led = set_red  # Red LED for WiFi fail/not ready yet
    blue_led = set_blue # Message received

# Default is to have only one LED and use that both for WiFi problems
# and for message RX
else:
    wifi_led = led
    blue_led = led

#if platform == 'pyboard':
#    from pyb import LED
#    def ledfunc(led, init):
#        led = led
#        led.on() if init else led.off()
#        def func(v):
#            led.on() if v else led.off()
#        return func
#    wifi_led = ledfunc(LED(1), 1)
#    blue_led = ledfunc(LED(3), 0)
