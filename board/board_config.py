# board_config contains the configuration of the board, including which modules to load&run
# as well as settings for those modules.
# Copyright © 2020 by Thorsten von Eicken.

import board_secrets as secrets

# kind tells us which type of board this is running it is used in board to define LED pins
kind = "nodemcu"                                                        # <----- UDPATE
#kind = "tve-bare"
#kind = "lolin-d32"
#kind = "huzzah32"
#kind = "tinypico"
#kind = "esp32thing"
#kind = "ezsbc"

# location is the system name and is used in mqtt topics, etc
location = "mqtest"                                                     # <----- UDPATE

# directories to add to the system search path (after ["", "/lib"])
# this is not applied in safe mode
syspath = ["/src"]

# experimental settings to control MicroPython heap size, may move elsewhere...
# max_mp_heap = 300*1024  # max MP heap in bytes to limit GC with SPIRAM, or leave free space
# min_idf_heap = 120*1024  # min bytes left for esp-idf for wifi/tls/ble/... buffers

#
# Configuration of loaded modules
#
# The dicts below get passed to the start() function of the modules loaded by main.py.
# The name of each dict must match the name of the module.

mqtt = {  # refer to mqtt_async for the list of config options
    # broker info
    "server"    : secrets.mqtt_addr,
    "client_id" : "esp32/test-" + location,                             # <----- UDPATE/REMOVE
    # settings to make TLS work
    "port"      : 4883,                                                 # <----- UDPATE/REMOVE
    "ssl_params": { "server_hostname": secrets.mqtt_host },
    # user/pass for MQTT-level authentication
    "user"      : "esp32/test",                                         # <----- UDPATE
    "password"  : secrets.mqtt_pass,
    # ssid/pass for Wifi auth
    "ssid"      : secrets.wifi_ssid,
    "wifi_pw"   : secrets.wifi_pass,
}

mqrepl = {
    "prefix" : mqtt["user"] + "/mqb/",  # prefix is before cmd/... or reply/...
}

watchdog = {
    "prefix"  : mqrepl["prefix"],  # must be mqrepl["prefix"]
    "timeout" : 120,   # watchdog timeout in seconds, default is 300
    "allok"   : 180,   # wait time in secs after connection before giving all-OK (no safe mode)
    "revert"  : True,  # whether to revert from safe mode to normal mode after all-OK time
}

logging = {
    "topic"      : mqtt["user"] + "/log",
    "boot_sz"    : 10*1024,  # large buffer at boot, got plenty of memory then
    "boot_level" :   10,     # 10=debug, 20=info, 30=warning (avoiding import logging)
    "loop_sz"    : 1024,     # more moderate buffer once connected
    "loop_level" :   20,     # 10=debug, 20=info, 30=warning (avoiding import logging)
}

# modules to load and call start(mqtt, config) on
modules = [ "mqtt", "logging", "mqrepl", "watchdog" ]
