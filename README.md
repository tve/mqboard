# MicroPython MQTT Framework

This repository contains a Framework for using MQTT with asyncio on MicroPython boards,
primarily on the ESP32. The `mqtt_async` library can be used stand-alone as a robust
MQTT client library designed for asyncio. The rest of this repo forms a mini framework
designed to operate MQTT-connected nodes remotely with great flexibility and robustness.

## Goals and features

Everything in this repo is engineered for systems that:
- run at some remote location and need to be managed from a distance, i.e., without plugging
  them into the USB port of some computer, and
- use a single encrypted connection, specifically, an MQTT connection to a broker.

By using a single connection only one set of TLS buffers is needed (20KB per connection, ouch!),
and there are no per-board certificates to maintain. There are also no open ports an attacker
could target.

The above goals make the following features desirable:
- Everything must be designed to stay up 24x7 and recover from failures.
- REPL access: being able to access the repl on each board via MQTT in order to run diagnostics,
  perform upgrades, or otherwise troubleshoot.
- OTA update: being able to send a MicroPython firmware update via MQTT.
- Modules: being able to add or update functional modules easily and with minimal impact
  on existing modules.
- Remote logging of ideally everything normally printed to the serial console via MQTT.
- Crash logging to some local persistent store so crashes can be analyzed remotely after the board
  resets.
- Watchdog timer and safe mode after successive crashes to ensure the board always
  comes up and can be accessed via MQTT even if the application misbehaves.

Currently all these features except for the crash log to local storage are implemented.

## Contents

The contents of this repo is:
- `mqtt_async` contains an MQTT client library that uses asyncio, is optimized for streaming files,
  and forms the backbone of most other libraries and tools here. It is used by other parts of the
  repo but can easily be used stand-alone.
- `mqrepl` contains a library to access the REPL via MQTT, basically to be able to send filesystem
  and interactive commands via MQTT.
- `mqboard` contains a python commandline tool to be run on a developer's machine to send commands
  to `mqrepl`. The directory also contains a watchdog and support for a safe mode.
- `board` contains `boot.py` and `main.py` that make it easy to add modules to a board.
  The directory also contain a `logging.py` implementation that functions via MQTT.

Additional modules of interest can be found in https://github.com/tve/mpy-lib, specifically:
- `sntp` to synchronize time
- `sysinfo` to send periodic MQTT messages with memory and other system info

Finally, some of the functionality depends on enhancements to MicroPython that are stuck
in pull requests on mainline. These can be found integrated into the `tve` branch of
https://github/tve/micropython.

## Testing

Everything in this repository is subject to CI testing. Some of the tests are run on Linux
using CPython but the majority are actually executed on an ESP32 using gohci.

## Getting started

### Prerequisites

- MQTT broker, preferably local, preferably supporting TLS (MQTTS), preferably using public
  certificante, e.g. from Let's Encrypt.
- ESP32 pre-loaded with a version of MicroPython supporting the "new asyncio", i.e. post-v1.12, 
  preferably TvE's fork (https://github.com/tve/micropython)

## First steps

- in `./board` copy `board_config_tmpl.py` to `board_config.tmpl` and update the values to suit your
  environment
- plug your esp32 into USB
- run `./load.sh` to load all the necessary files
- try a repl command: `./mqboard/mqboard  -s <your_broker> -p 1883/8883 -t esp32/test/mqb eval
  '2+3'`:
```
    DEBUG:mqboard:Connecting to core.voneicken.com:1883
    DEBUG:mqboard:Connected! Subscribing to esp32/test/mqb/reply/out/_PIFFncP
    INFO:mqboard:Pub esp32/test/mqb/cmd/eval/_PIFFncP #0 last=1 len=5
    DEBUG:mqboard:done publishing
    DEBUG:mqboard:Received reply on topic 'esp32/test/mqb/reply/out/_PIFFncP' with QoS 1
    5
    INFO:mqboard:0.006kB in 0.126s -> 0.046kB/s
```
  (The eval result is the line with the "5", mqboard needs to turn those debug log statement off
  by default...)
- tip: if nothing happens, verify which topic the mqrepl subscribes to:
  - use miniterm.py or equivalent to watch the esp32 console and reset the esp32 (ctrl-t, ctrl-d two
    times in miniterm)
  - look for a line like `mqrepl: Subscribed to b'esp32/test/mqb/cmd/#'`, it's typically the last
    line printed
  - use the part before `/cmd/` in mqboard's `-t` argument

For help, please post on https://forum.micropython.org 

For license info see the LICENSE file.
