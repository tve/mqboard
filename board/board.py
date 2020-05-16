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
# act_led: network activity LED, typ. blue, turn on with act_led(True)
# fail_led: failure/error, type red, turn on with fail_led(True)
# For demos ensure the same calling convention for LEDs on all platforms.

led = False
bat_volt_pin = None
bat_fct = 2  # voltage divider factor

if kind == "tve-bare":
    # bare esp32-wroom module with LED across IO23 and gnd
    lpin = machine.Pin(23, machine.Pin.OUT, None, value=1)
    led = lambda v: lpin(v)
    act_led, fail_led = (led, led)
elif kind == "huzzah32":
    # Adafruit Huzzah32 feather
    lpin = machine.Pin(13, machine.Pin.OUT, None, value=1)
    led = lambda v: lpin(v)
    fail_led = led
elif kind == "lolin-d32":
    # Wemos Lolin D-32
    lpin = machine.Pin(5, machine.Pin.OUT, None, value=1)
    led = lambda v: lpin(not v)
    bat_volt_pin = machine.ADC(machine.Pin(35))
    bat_volt_pin.atten(machine.ADC.ATTN_11DB)
    act_led, fail_led = (led, led)
elif kind == "esp32thing":
    # Sparkfun ESP32 Thing
    lpin = machine.Pin(5, machine.Pin.OUT, None, value=1)
    led = lambda v: lpin(v)
    act_led, fail_led = (led, led)
elif kind == "ezsbc":
    # EzSBC
    lpin = machine.Pin(19, machine.Pin.OUT, None, value=1)
    blue_led = lambda v: lpin(not v)
    lpin = machine.Pin(16, machine.Pin.OUT, None, value=1)
    red_led = lambda v: lpin(not v)
    # bat_volt_pin = machine.ADC(machine.Pin(35))
    # bat_volt_pin.atten(machine.ADC.ATTN_11DB)
    act_led, fail_led = (blue_led, red_led)
elif kind == "tinypico":
    # TinyPICO has an RGB LED so we use the red channel for WiFi and the blue
    # channel for message rx
    from led import dotstar

    color = [255, 0, 0]

    def set_red(v):
        color[0] = 255 if v else 0
        dotstar[0] = color

    def set_blue(v):
        color[2] = 255 if v else 0
        dotstar[0] = color

    fail_led = set_red
    act_led = set_blue


def get_battery_voltage():
    """
    Returns the current battery voltage. If no battery is connected, returns 3.7V
    This is an approximation only, but useful to detect if the battery is getting low.
    """
    if bat_volt_pin == None:
        return 0
    measuredvbat = bat_volt_pin.read() / 4095
    measuredvbat *= 3.6 * bat_fct  # 3.6V at full scale
    return measuredvbat


# ===== MQTT stuff
# merge board-specific mqtt config into default config
# in the app use `mqtt_async.MQTTClient(mqtt_async.config)`
try:
    from mqtt_async import config

    config.update(mqtt_config)
except Exception:
    pass

# ===== Wifi stuff
# connect_wifi is a handy little function to manually connect wifi
def connect_wifi():
    import network

    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    print("Connecting to", wifi_ssid, "...")
    wlan.connect(wifi_ssid, wifi_pass)
    while not wlan.isconnected():
        pass
    print("Connected!")


# if platform == 'pyboard':
#    from pyb import LED
#    def ledfunc(led, init):
#        led = led
#        led.on() if init else led.off()
#        def func(v):
#            led.on() if v else led.off()
#        return func
#    wifi_led = ledfunc(LED(1), 1)
#    blue_led = ledfunc(LED(3), 0)
