# board_config contains magic strings that don't get published or checked into source control
from binascii import unhexlify

# kind tells us which type of board this is running
#kind = "lolin-d32"
kind = "huzzah32"

# location is the system name and is used in mqtt topics, etc
location = "mqtest"

wifi_ssid = 'my-ssid'
wifi_pass = 'my-pass'
mqtt_server = '192.168.0.1'
mqtt_ident = 'esp32-test'
mqtt_key = unhexlify(b'd9000000000000000000000000000024')
