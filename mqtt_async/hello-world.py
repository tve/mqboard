# Copyright © 2020 by Thorsten von Eicken.
from mqtt_async import MQTTClient, config
import uasyncio as asyncio
import logging
logging.basicConfig(level=logging.DEBUG)

# Change the following configs to suit your environment
TOPIC           = 'test/mqtt_async'
config.server   = '192.168.0.14' # can also be a hostname
config.ssid     = 'wifi-ssid'
config.wifi_pw  = 'wifi-password'

def callback(topic, msg, retained, qos): print(topic, msg, retained, qos)

async def conn_callback(client): await client.subscribe(TOPIC, 1)

async def main(client):
    await client.connect()
    n = 0
    while True:
        print('publish', n)
        await client.publish(TOPIC, 'Hello World #{}!'.format(n), qos=1)
        await asyncio.sleep(5)
        n += 1

config.subs_cb = callback
config.connect_coro = conn_callback

client = MQTTClient(config)
loop = asyncio.get_event_loop()
loop.run_until_complete(main(client))
