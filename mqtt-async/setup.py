import sys
# Remove current dir from sys.path, otherwise setuptools will peek up our
# module instead of system's.
sys.path.pop(0)
from setuptools import setup
sys.path.append("..")
import sdist_upip

setup(name='micropython-mqtt',
      version='0.7b4',
      description='Reliable MQTT client for MicroPython using asyncio',
      long_description="MQTT client for Micropython using asyncio.\n"\
      "The implementation requires the new (in 2020) uasyncio built into Micropython. It provides\n"\
      "an MQTTClient class that operates in the background (using the asyncio loop) and makes\n"\
      "callbacks for incoming messages. MQTTClient supports QoS 0 and QoS messages, and it supports\n"\
      "non-blocking publishing of messages to improve streaming performance.\n"\
      "MQTTClient automatically reconnects if the connection to the broker fails and also\n"\
      "automatically connects and reconnects Wifi should it drop.\n"\
      "The API is largely compatible with Peter Hinch's mqtt_as.",
      url='https://github.com/tve/micropython-mqtt',
      author='Thorsten von Eicken',
      maintainer='Thorsten von Eicken',
      license='MIT',
      cmdclass={'sdist': sdist_upip.sdist},
      py_modules=['mqtt_async'])
