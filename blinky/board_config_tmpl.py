# board_config contains magic strings that don't get published or checked into source control

kind = "nodemcu"

# teststa, antenna, home, ...
location = "blinky"

# info to connect to wifi
wifi_ssid = "MY-SSID"       <--- UPDATE
wifi_pass = "MY-PASSWD"     <--- UPDATE

# directories to add to the system search path (after ["", "/lib"]), not applied in safe mode
syspath = ["/src"]

#
# Configuration of loaded modules
#
# The dicts below get passed to the start() function of the modules loaded by main.py.
# The name of each dict must match the name of the module.

mqtt = {
    "server"     : "192.168.0.14",    <--- UPDATE
    "ssl_params" : { "server_hostname": "mqtt.example.com" },    <--- UPDATE/REMOVE
    "user"       : "esp32/blinky",                               <--- UPDATE/REMOVE
    "password"   : "00000000000000000000000000000000",           <--- UPDATE/REMOVE
    "ssid"       : wifi_ssid,
    "wifi_pw"    : wifi_pass,
}

# little convenience for blincky demo to support with and without mqtt["user"]
mqtt_prefix = mqtt.get("user", "esp32/" + location)

sntp = {
    "host"   : "pool.ntp.org",
    "zone"   : "PST+8PDT,M3.2.0/2,M11.1.0/2",   <--- UPDATE
}

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
    "boot_sz"    : 10*1024,  # large buffer at boot, got plenty of memory
    "boot_level" :   10,     # 10=debug, 20=info, 30=warning (trying not to import logging)
    "loop_sz"    : 2048,     # more moderate buffer once entering run loop
    "loop_level" :   10,     # 10=debug, 20=info, 30=warning (trying not to import logging)
}

# sysinfo task sends memory, uptime, and wifi info periodically
sysinfo = {
    "topic"      : mqtt_prefix + "/sysinfo",
    "interval"   : 20,  # interval in seconds, default is 60
}

blinky = {
    "topic"  : mqtt_prefix + "/period",
    "period" : 800,  # initial period in milliseconds
}

# modules to load and call start(mqtt) on
from __main__ import safemode
modules = [ "mqtt", "sntp", "logging", "mqrepl", "watchdog" ]
if not safemode:
    modules += [ "blinky" ]
