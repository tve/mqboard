Blinky Demo for MQBoard
=======================

The blinky demo app blinks an LED at a rate controlled via MQTT. Its purpose is to explore running
in normal mode vs. in safe-mode and seeing the various logging options as well as file
synchronization. The code also has simple examples for subscribing to messages, receiving messages,
and sending messages.

### Try it out

This section assumes you completed the "first steps" in `../README.md`, i.e. you have the board
up and running in safe-mode.

The first step is to prepare a `board_config.py` (again). The difference between this board config
and the one in the board directory is that the mqtt prefix is now esp32/blinky (you can change that
of course) and it includes SNTP to sync time, a sysinfo background task, and the blinky app:
```
cp board_config_tmpl.py board_config.py
vim board_config.py # edit clearly marked lines
```

Update the safe mode files on the board over MQTT. Note that the command below assumes your board is
configured according to the "first steps" and thus the repl is subscribed to `esp32/test/mqb`. After
the update and a reset it will instead subscribe to `esp32/blinky/mqb` (you still have the
window/pane/tab running showing the board's terminal output, right?).
```
$ ./sync-safemode --prefix esp32/test
Target directory /safemode
  put  missing ./mpy-lib/sntp.py -> /safemode/sntp.py
  ok   main.py
  ok   logging.py
  ok   board.py
  ok   mqtt.py
  ok   mqrepl.py
  ok   watchdog.py
  ok   mqtt_async.py
  put  shadiff ./board_config.py -> /safemode/board_config.py
Target directory /
  ok   boot.py
```
If your shell doesn't like the `#!` at the top of `sync-safemode` you can also use
`../mqboard/mqboard --prefix esp32/test sync sync-safemode`.
The output shows that one file was missing (`sntp.py`) and one file changed (`board_config.py`).

In the terminal window you should have seen log lines that indicate repl activity:
```
I 111425   mqrepl: Dispatch eval, msglen=530 seq=0 last=True id=DffT_1E2 dup=0
```
as well as text output by those commands as part of an `exec()`:
```
'mqrepl.py':'de77a2b153c806b0dd59f1fb1ac4f7ccf56fe291'
```
Those lines are captured by the repl and sent back over MQTT where the `mqboard sync` tool
uses them (the line above is the SHA1 of the `mqrepl.py` file used to determine whether the
file is up-to-date).

Optionally open another terminal window/pane/tab and run `../mqboard/mqboard --prefix
esp32/blinky view`.

Now reset the board and watch the USB log show about the same as previously. Once the board connects
to MQTT you should see the other terminal window running `mqboard view` replay most of the log.
Except for the ESP-IDF lines that are missing, it should be identical. These log lines were
buffered in memory until the conenction was established and the board config controls the max
amount of buffering.

Something else you should notice is that the timestamps on the log lines switch from
milliseconds-since-boot to hours, minutes, seconds and milliseconds.
(The hour may not be correct due to some caching in the logger that causes the time zone not to
be applied until the top of the next hour: that's an open issue.)

Note that there is a time-out on safe mode (set to 3 minutes in the board config) after which it
attempts to switch back to normal mode if the watchdog is ticking along fine. If that happens you
will see a magenta message `C 00:58:54.405 watchdog: Switching to NORMAL MODE via reset`. Just wait
until it's connected again...

Finally it's time to load the blinky app:
```
$ ./sync --prefix esp32/blinky
Target directory /lib
  mkdir /lib
  put  missing ./mpy-lib/sntp.py -> /lib/sntp.py
  put  missing ./mpy-lib/sysinfo.py -> /lib/sysinfo.py
  put  missing ../board/logging.py -> /lib/logging.py
  put  missing ../board/board.py -> /lib/board.py
  put  missing ../board/mqtt.py -> /lib/mqtt.py
  put  missing ../mqrepl/mqrepl.py -> /lib/mqrepl.py
  put  missing ../mqrepl/watchdog.py -> /lib/watchdog.py
  put  missing ./../mqtt_async/mqtt_async.py -> /lib/mqtt_async.py
Target directory /src
  mkdir /src
  put  missing ./blinky.py -> /src/blinky.py
Target directory /
  put  missing ../board/main.py -> /main.py
  ok   board_config.py
  put  missing ../board/boot.py -> /boot.py
```

Reset the board via MQTT:
```
$ ../mqboard/mqboard --prefix esp32/blinky reset
C 01:06:11.400     main: Resetting via mqboard safemode=False
```
The LED on your board should now be blinking a little faster than 1Hz. let's slow it down.
You will need to dig up your favorite tool for sending an MQTT message to your broker
to the topic `esp32/blinky/period` with a message contents of the period in milliseconds as
ascii string. Here's how this looks for me:
```
$ mosquitto_pub -h 192.168.0.14 -u core -t esp32/blinky/period -m "2000"
```
And the LED should now blink at 0.5Hz.

With a little patience you can see one of the sysinfo messages, which is
sent once every 20 seconds, so you may have to way for a bit. Note that `--topic`
is used instead of `--prefix` to provide the exact topic:
```
$ ../mpy-mqtt/mqboard/mqboard --topic esp32/blinky/sysinfo view
{"up":13,"free":65632,"cont_free":43488,"mqtt_conn":1}
```
The message shows an uptime of 13 seconds, 64KB of free memory, a largest free block of 43KB,
and one MQTT connection (this is a reconnection counter, not a count of concurrent connections as
there is always at most one).

Next steps:
- to see how the blinky app is coded, look into `blinky.py`
- to learn more about how the board boots and starts the app, as well as safe mode see
  the README in the board directory
- to learn more about the MQTT Repl, see the README in the mqrepl directory
- to learn more about the mqboard command line too, see the README in the mqboard directory
