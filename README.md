# MicroPython MQTT Framework

This repository contains a micro-framework for using MQTT with asyncio on MicroPython boards,
primarily on the ESP32. The `mqtt_async` library can be used stand-alone as a robust
MQTT client library designed for asyncio. The rest of this repo forms a micro-framework
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

### Open issues

The main open (high-level) issue is low power operation. Right now power is not taken into
consideration and, in particular, the start-up time is not optimized to enable periodic wake-up
operation on batteries.

OTA firmware upgrades and safe mode are currently not integrated, which means that an OTA upgrade
requires more care and thought than it should.

The `mqtt_async` implementation tries to be compatible with Peter Hinch's `mqtt_as` and it's time to
depart from that so the functionality in `board/mqtt.py` can be integrated directly and so the
management of Wifi can be decoupled.

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

The getting-started consists of three steps:
1. Set-up some prerequisites
2. Load the board with the safemode software, from there on it can be managed over MQTT
3. Try out the sample blinky app (blinks the LED on the board at a frequency that can be controlled
   over MQTT.

### Prerequisites

- MQTT broker, preferably local, preferably supporting TLS (MQTTS), preferably using a public
  certificate, e.g. from Let's Encrypt.
- ESP32 pre-loaded with TvE's version of MicroPython supporting the "new asyncio", i.e. post-v1.12, 
  as well as a functioning `RTC.memory()`, asyncio with TLS, and a bunch of other bug fixes: 
  https://github.com/tve/micropython.
- The micropython repository (https://github.com/micropython/micropython) or at least the
  `pyboard.py` tool from its `tools` directory.
- The Python click and paho-mqtt packages: `pip install click paho-mqtt`.

### Loading up safemode

Loading up the files that make up safe-mode is initially done over USB. Later on they can be updated
over MQTT, but we need to bootstrap first.

1. Wipe the esp32's filesystem clean (you don't need this if you just did a flash erase and
   loaded the firmware):
```
    $ /home/src/esp32/micropython/tools/pyboard.py board/rm_rf.py
    rmdir contents: /
    rm //boot.py
    rm //main.py
```
2. Copy the config file template to `board/board_config.py`, and modify it to suit your
environment, e.g.:
```
    cp board/board_config_tmpl.py board/board_config.py
    vim board/board_config.py
```
   The lines you need to edit are clearly marked.
3. Load the files (adjust the path to the tools dir and the device name):
```
    $ PATH=/home/src/esp32/micropython/tools:$PATH PYBOARD_DEVICE=/dev/ttyUSB0 ./load.sh
    device: /dev/ttyUSB0
    cp ./board/boot.py :boot.py
    mkdir :/safemode
    cp ./board/main.py :/safemode/main.py
    cp ./board/board.py :/safemode/board.py
    cp ./board/logging.py :/safemode/logging.py
    cp ./board/mqtt.py :/safemode/mqtt.py
    cp ./mqrepl/mqrepl.py :/safemode/mqrepl.py
    cp ./mqrepl/watchdog.py :/safemode/watchdog.py
    cp ./mqtt_async/mqtt_async.py :/safemode/mqtt_async.py
    cp ./board/board_config.py :/safemode/board_config.py
```
4. Open a new terminal window/tab/pane you can keep open to watch what the board is doing and
   connect, ideally with a pgm that supports ANSI color escape sequences (sadly, colors don't show
   here). Then either press the reset button on the board or toggle DTR (in minicom that's ctrl-t
   ctrl-d two times, in picocom that's ctrl-a ctrl-p):
```
    $ miniterm2.py --filter direct /dev/ttyUSB0 115200
    --- Miniterm on /dev/ttyUSB0  115200,8,N,1 ---
    --- Quit: Ctrl+] | Menu: Ctrl+T | Help: Ctrl+T followed by Ctrl+H ---
    --- DTR inactive ---
    --- DTR active ---
    ets Jun  8 2016 00:22:57

    rst:0x1 (POWERON_RESET),boot:0x13 (SPI_FAST_FLASH_BOOT)
    ...
    I (579) cpu_start: Starting scheduler on PRO CPU.
    I (0) cpu_start: Starting scheduler on APP CPU.
    Traceback (most recent call last):
      File "boot.py", line 51, in <module>
    ImportError: no module named 'logging'
    Switching to SAFE MODE
    W 1394     main:

    W 1401     main: MicroPython 1.12.0 (v1.12-weather-1-8-g251c8f5a3 on 2020-05-23)
    W 1408     main: 4MB/OTA NO-BT module with ESP32
    W 1414     main: esp32/test mqtest starting at (1970, 1, 1, 0, 0, 1, 3, 1, 0)

    W 1423     main: Boot partition: ota_0
    W 1431     main: SAFE MODE boot (normal mode failed)
    W 1460     main: Reset cause: PWRON_RESET
    I 1578     main: MEM free=101424 contig=94752
    ...
    I (9198) network: CONNECTED
    I (9234) wifi: AP's beacon interval = 102400 us, DTIM period = 1
    I (10053) tcpip_adapter: sta ip: 192.168.0.106, mask: 255.255.255.0, gw: 192.168.0.1
    I (10055) network: GOT_IP
    I 7080 mqtt_async: Connecting to ('192.168.0.14', 4883) id=esp32/test-mqtest clean=1
    I 9244 mqtt_async: Connecting to ('192.168.0.14', 4883) id=esp32/test-mqtest clean=0
    I 11166     mqtt: Initial MQTT connection (->3)
    I 11175     main: Logging to esp32/test/log
    I 11182     main: Log buf: 1350/10240 bytes
    I 11214     mqtt: MQTT connected (->0)
    I 11474     main: Log buf: 754/1024 bytes
    I 11569   mqrepl: Subscribed to esp32/test/mqb/cmd/#
    I 11607 watchdog: esp32/test/mqb/cmd/eval/0F00D/
    I 11664   mqrepl: Dispatch eval, msglen=15 seq=0 last=True id=0F00D dup=0
    ...
```
   What you see is are the initial boot messages from ESP-IDF followed by a python exception,
   which is from `boot.py` trying to load the logger from the application. But we've only loaded
   safe-mode files so far, hence the exception. As a result, `boot.py` switches to safe-mode and
   proceeds. Then main prints some hello-world info and starts loading the modules comprising
   the safe-mode application. These start wifi, connect via MQTT, and at the end you see the
   watchdog sending a round-trip message to the MQTT Repl to feed the WDT timer. Your board is
   now up!
5. Try something:
```
    $ mqboard/mqboard --prefix esp32/test eval '45+876'
    921
```
   The prefix corresponds to the part before the "/mqb" in the log message `I 11569   mqrepl:
   Subscribed to esp32/test/mqb/cmd/#` (it's the `mqtt_prefix` variable in `board_config.py`).

You can now proceed to the blinky demo app.


For help, please post on https://forum.micropython.org 

For license info see the LICENSE file.
