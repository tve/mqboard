# board_config contains magic strings that don't get published or checked into source control
from binascii import unhexlify

# kind tells us which type of board this is running
kind = "huzzah32"
#kind = "lolin-d32"
#kind = "ezsbc"

# location is the system name and is used in mqtt topics, etc
location = "mqtest"

wifi_ssid = 'my-ssid'
wifi_pass = 'my-pass'

# info to connect to mqtt broker, the keys in this hash match mqtt_async.MQTTConfig and get merged
# into the default mqtt_async.config. This means that what's not meaningful below can be left out.
mqtt_config = {
    "server"    : '192.168.0.14',  # required
    "port"      : 8883,  # default is 1883 unless ssl_params is set, then it's 8883
    "ssl_params": { "server_hostname": "broker.example.com" },
    "client_id" : 'esp32-test-' + location,  # mac address is default
    "user"      : 'test/esp32',  # user/password required for authenticating broker
    "password"  : '00000000000000000000000000000000',
    "ssid"      : wifi_ssid,  # ssid/pass required unless wifi is already connected
    "wifi_pw"   : wifi_pass,
}

# minimal mqtt_config:
# mqtt_config = { "server": "mqtt.local" }

# SNTP config
sntp_config = {
    "host"   : "pool.ntp.org",
    "zone"   : "PST+8PDT,M3.2.0/2,M11.1.0/2",
}

# MQRepl config
mqrepl_config = {
    # prefix before '/mqb/cmd/...', '/mwb/reply/...', etc.
    "prefix" : mqtt_config.get("user", b"esp32/" + location),
}

# Modules to load and call start on. For module foo, if this file defines foo_config then
# foo.start(mqtt, foo_config) is called, else foo.start(mqtt). If there is no foo.start() then
# that's OK too.
modules = [ "mqrepl", "mqwdt", "sntp" ]
