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
    "server"   : '192.168.0.14',
    "port"     : 8883,
    "hostname" : 'broker.example.com',
    "ident"    : 'esp32-test-' + location,
    "user"     : 'test/esp32',
    "passwd"   : '00000000000000000000000000000000',
}
