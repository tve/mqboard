MQTT-based REPL for Micropython
===============================

MQRepl provides REPL-like access via MQTT. It's not really a REPL in that it is not designed to
provide the same interactive feel as the serial console REPL. Instead, it provides `pyboard`-like
commands to upload/download files and to exec or eval python source code fragments. In addition, it
supports the OTA (Over The Air) upgrade of the MicroPython firmware.

## MQRepl commands

The MQRepl implements a minimal number of commands. Additional commands (`rm`, `mkdir`, ...)
are implemented by `mqboard` using eval/exec. The commands are:

- __PUT__: write a file to the board's filesystem, the file is streamed using many MQTT messages
- __GET__: read a file from the board's filesystem, the file is streamed using many MQTT messages
- __EVAL__: a fragment of Python code is sent to the board in one message (this limits the
  size of the fragment to what can be handled in memory) and `eval` or `exec`'s it, the `repr` of
  the result of eval or the output of exec is sent back
- __OTA__: a new version of the MicroPython firmware is streamed to the board using many MQTT
  messages, written to the next OTA flash partition, and marked for being booted at the next reset

Notes:
- A file PUT to the board is checked using its SHA1, however an incorrect SHA just results in an
  error being sent back, the bad data is still written, which may clobber an existing version.
  This could be enhanced to write to a temp file and then rename that on success.
- The output of eval is sent back in one message and its size is limited by what can be handled in
  memory.
- The output of exec is captured in a fixed-size buffer and its size is thus limited (to
  `BUFLEN` defined in `mqrepl.py`).
- The EVAL command first tries to compile the source code for eval and if that fails it tries
  exec. This is pretty much what the console REPL does. A previous version had separate commands
  for eval and exec. Both have their pros and cons but the combined eval/exec is a bit smaller.

## Watchdog

_The board must remain manageable at all times._

The premise of the watchdog implementation is that it must be possible to regain remote control of
the board within a specified time period, assuming that communication is possible, of course.
This is implemented by the `watchdog` module along with support for the safe mode.

The way the watchdog process works is that it sends an EVAL command to the MQTT broker with the
topic of the board's MQRepl. The command executed by the EVAL feeds the watchdog timer (i.e.
prevents it from timing out and thereby resetting the board). This way, successful feeding is 
proof that an admin can send the board commands to control it.

The watchdog also keeps track of the safe mode vs normal boot switch: a configurable number of
seconds after the first successful feeding it writes the magic value into RTC memory top cause
the next boot to be in normal mode.
Put differently, the board continues to boot into normal mode if at each boot there is
a window during which it can be controlled remotely.

Finally, if booted into safe mode, the watchdog can reset the board into normal mode if feeding
succeeds for the configured time-period.

Notes:
- The current implementation of the normal/safe switch is simplistic: it will eventually write
  the magic even if only a single feeding succeeds, which may not be enough to regain control.
- The watchdog does not tie into any application functionality, it's purely about the board
  being controllable. This clearly could be enhanced.
