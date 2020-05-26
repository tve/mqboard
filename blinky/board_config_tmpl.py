# board_config contains magic strings that don't get published or checked into source control

# kind tells us which type of board this is running, it is used in board to define LED pins
kind = "nodemcu"
#kind = "huzzah32"
#kind = "lolin-d32"
#kind = "esp32thing"
#kind = "tinypico"
#kind = "ezsbc"

# location is the system name and is used in mqtt topics, etc
location = "blinky"

wifi_ssid = "MY-SSID"       <--- UPDATE
wifi_pass = "MY-PASSWD"     <--- UPDATE

# directories to add to the system search path (after ["", "/lib"]), not applied in safe mode
syspath = ["/src"]

#
# Configuration of loaded modules
#
# The dicts below get passed to the start() function of the modules loaded by main.py.
# The name of each dict must match the name of the module.

mqtt = {  # refer to mqtt_async for the list of config options
    "server"     : "192.168.0.14",                               <--- UPDATE
    "ssl_params" : { "server_hostname": "mqtt.example.com" },    <--- UPDATE/REMOVE
    "user"       : "esp32/blinky",                               <--- UPDATE/REMOVE
    "password"   : "00000000000000000000000000000000",           <--- UPDATE/REMOVE
    "ssid"       : wifi_ssid,
    "wifi_pw"    : wifi_pass,
}

# little convenience for demo to support with and without mqtt["user"]
mqtt_prefix = mqtt.get("user", "esp32/" + location)

mqrepl = {
    "prefix" : mqtt_prefix + "/mqb/",  # prefix is before cmd/... or reply/...
}

watchdog = {
    "prefix"  : mqrepl["prefix"],  # must be mqrepl["prefix"]
    "timeout" : 120,   # watchdog timeout in seconds, default is 300
    "allok"   : 180,   # wait time in secs after connection before giving all-OK (no safe mode)
    "revert"  : True,  # whether to revert from safe mode to normal mode after all-OK time
}

logging = {
    "topic"      : mqtt_prefix + "/log",
    "boot_sz"    : 10*1024,  # large buffer at boot, got plenty of memory then
    "boot_level" :   10,     # 10=debug, 20=info, 30=warning (avoiding import logging)
    "loop_sz"    : 1024,     # more moderate buffer once connected
    "loop_level" :   10,     # 10=debug, 20=info, 30=warning (avoiding import logging)
}

# network time sync; from github.com/tve/mpy-lib/sntp
sntp = {
    "host"   : "pool.ntp.org",
    "zone"   : "PST+8PDT,M3.2.0/2,M11.1.0/2",   <--- UPDATE
}

# sysinfo task sends system info periodically; from github.com/tve/mpy-lib/sysinfo
sysinfo = {
    "topic"      : mqtt_prefix + "/sysinfo",
    "interval"   : 20,  # interval in seconds, default is 60
}

blinky = {
    "topic"  : mqtt_prefix + "/period",
    "period" : 800,  # initial period in milliseconds
}

# Modules to load and call start on. For module foo, if this file defines foo then
# foo.start(mqtt, foo) is called, else foo.start(mqtt, {}). If there is no foo.start() then
# that's OK too.
from __main__ import safemode
modules = [ "mqtt", "sntp", "logging", "mqrepl", "watchdog" ]
if not safemode:
    modules += [ "sysinfo", "blinky" ]
