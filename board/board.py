# Board configuration so other modules don't need to be too board-specific
import machine

# Pull-in the specifics of the board from `board_config`. That should be the only file that is
# customized for each board. It also contains passwords and keys and should thus not be checked into
# version control. There should be a `board_confgi_tmpl.py` file around to use as template.
# board_config needs to define:
# - kind: board type name, like huzzah32, lolin-d32, ... used to pick the pin for the LED, etc
# - location: short name for this board used in mqtt topics
# - wifi_ssid: SSID to connect to
# - wifi_pass: password
# - mqtt_server: IP address or hostname
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
elif kind == "huzzah32":
    # Adafruit Huzzah32 feather
    lpin = machine.Pin(13, machine.Pin.OUT, None, value=1)
    led = lambda v: lpin(v)
elif kind == "lolin-d32":
    # Wemos Lolin D-32
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
# merge board-specific mqtt config into default config
# in the app use `mqtt_async.MQTTClient(mqtt_async.config)`
try:
    from mqtt_async import config
    config.update(mqtt_config)
except Exception:
    pass

# ===== LED stuff
# For demos ensure the same calling convention for LEDs on all platforms.
# ESP8266 Feather Huzzah reference board has active low LEDs on pins 0 and 2.
# ESP32 is assumed to have user supplied active low LEDs on same pins.
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
