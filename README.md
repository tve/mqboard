# MicroPython MQTT

This repository contains libraries and tools for using MQTT with asyncio on MicroPython boards,
primarily on the ESP32.

## Goals and features

Everything in this repo is engineered for systems that run at some remote location and need to be
managed from a distance, i.e., preferably without plugging them into the USB port of some computer.
Another goal is to use a single encrypted connection, specifically, an MQTT connection to a broker.
This way there is only one set of TLS buffers (20KB per connection, ouch!), and there are no
per-board certificates to maintain.

The above goals make the following features desirable:
- Everything must be designed to stay up 24x7 and recover from failures.
- REPL access: being able to access the repl on each board via MQTT in order to run diagnostics,
  perform upgrades, or otherwise troubleshoot.
- OTA update: being able to send a MicroPython firmware update via MQTT.
- Remote logging of ideally everything normally printed to the serial console via MQTT.
- Crash logging to some local persistent store so crashes can be analyzed remotely after the board
  resets.
- Watchdog timer and application lock-out after successive crashes to ensure the board always
  comes up and can be accessed via MQTT even if the application misbehaves.

In its current state the first two features are implemented, the third is work-in-progress, and the
last two are still on the to-do list.

## Contents

The contents of this repo is:
- `mqtt_async` contains an MQTT client library that uses asyncio, is optimized for streaming files,
  and forms the backbone of most other libraries and tools here.
- `mqrepl` contains a library to run a REPL via MQTT, basically to be able to send filesystem and
  interactive commands to a MicroPython board via MQTT.
- `mqboard` contains a python commandline tool to be run on a developer's machine to send commands
  to `mqrepl`.
- `board` contains sample `boot.py`, `main.py`, etc. files to populate a board for use my `mqrepl`.

## Testing

Everything in this repo is subject to CI testing. Some of it consists of testing python code on


## Getting started

### Prerequisites

- MQTT broker, preferably local, preferably supporting TLS (MQTTS), preferably using public
  certificante, e.g. from Let's Encrypt.
- ESP32 pre-loaded with a version of MicroPython supporting the "new asyncio", i.e. post-v1.12, 
  preferably TvE's fork (github.com/tve/micropython)

## First steps

- in `./board` copy `board_config_tmpl.py` to `board_config.tmpl` and update the values to suit your
  environment
- plug your esp32 into USB
- run `./load.sh` to load all the necessary files
- try a repl command: `./mqboard/mqboard.py  -s <your_broker> -p 1883/8883 -t test/esp32/mqtest eval
  '2+3'`

For help, please post on https://forum.micropython.org 

For license info see the LICENSE file.
