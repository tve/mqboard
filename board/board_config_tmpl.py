# board_config contains magic strings that don't get published or checked into source control

# kind tells us which type of board this is running, it is used in board to define LED pins
kind = "nodemcu"
#kind = "huzzah32"
#kind = "lolin-d32"
#kind = "ezsbc"

# location is the system name and is used in mqtt topics, etc
location = "mqtest"

wifi_ssid = 'my-ssid'
wifi_pass = 'my-pass'

# directories to add to the system search path (after ["", "/lib"])
# this is only applied on normal boot, not in safe mode
syspath = ["/src"]

#
# Configuration of loaded modules
#
# The dicts below get passed to the start() function of the modules loaded by main.py.
# The name of each dict must match the name of the module.

mqtt = {  # refer to mqtt_async for the list of config options
    "server"    : '192.168.0.14',  # required
    "port"      : 8883,  # default is 1883 unless ssl_params is set, then it's 8883
    "ssl_params": { "server_hostname": "broker.example.com" },
    "client_id" : 'esp32-test-' + location,  # mac address is default
    "user"      : 'test/esp32',  # user and password for authenticating with broker
    "password"  : '00000000000000000000000000000000',
    "ssid"      : wifi_ssid,  # ssid/pass required unless wifi is already connected
    "wifi_pw"   : wifi_pass,
}

sntp = {  # from github.com/tve/mpy-lib/sntp
    "host"   : "pool.ntp.org",
    "zone"   : "PST+8PDT,M3.2.0/2,M11.1.0/2",
}

mqrepl = {
    "prefix" : mqtt.get("user", b"esp32/" + location) + "/mqb/",  # prefix is before cmd/...
}

watchdog = {
    "prefix"  : mqrepl["prefix"],  # must be mqrepl["prefix"]
    "timeout" : 300,   # watchdog timeout in seconds, default is 300
    "allok"   : 120,   # wait time in secs after connection before giving all-OK (no safe mode)
    "revert"  : True,  # whether to revert from safe mode to normal mode after all-OK time
}

logging = {
    "topic"      : mqtt["user"] + "/log",
    "boot_sz"    : 10*1024,  # large buffer at boot, got plenty of memory then
    "boot_level" :   10,     # 10=debug, 20=info, 30=warning (avoiding import logging)
    "loop_sz"    : 1024,     # more moderate buffer once connected
    "loop_level" :   20,     # 10=debug, 20=info, 30=warning (avoiding import logging)
}

# Modules to load and call start on. For module foo, if this file defines foo then
# foo.start(mqtt, foo) is called, else foo.start(mqtt, {}). If there is no foo.start() then
# that's OK too.
modules = [ "mqtt", "logging", "mqrepl", "watchdog" ]
