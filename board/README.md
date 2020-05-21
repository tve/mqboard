Micropython board configuration and task loader
===============================================

This directory contains `boot.py`, `main.py` and associated files to initialize a board
so it can run an `asyncio` main loop with MQTT and automatically load a number of
functional components (mqtt repl, watchdog, sntp, application, etc).

## Board configuration

_All files but one should be the same on all boards._

The intent is that boards can be initialized easily because files with code can just be updated and
do not need to be tweaked for each board. There is only one file which is board-specific and that
does not contain any real code, just settings. This also makes it easy to maintain a public git
repository because everything but this one file can be made public without worrying about
information leakage.

Specifically, everything in this repo is common to all boards, except for the `board_config.py`
file, which is missing, and for which a template is provided in `board_config_tmpl.py`.

## Launching asyncio tasks

_All functional components are listed in `board_config.py` and started via `module.start()`_

The way a board is told which components to run is by listing them in `board_config.py` and
by forcing a convention, which is that each component consists of a python module that exposes
a module-level `start()` function that starts all activities of the module.

The start function is passed a handle onto an `MQTT` object that provides access to the
MQTT client and that supports registration of callbacks. It is also passed its config dict
coming from the `board_config.py`.

The start function is expected to
instantiate objects used by the components and to create asyncio tasks as necessary.

## Component independence

_Functional components should not depend on the board configuration machinery_

By exposing a `start` function that is passed a handle onto MQTT and onto a config dict
components can be written to be independent of the specific board configuration machinery and of the
MQTT client (other than the signature of pub/sub functions). This means that components should not
`import board` directly making reuse across projects easier.

## Identity

Establishing or setting a board's identity is always tricky and there are several forms of identity
in play. The following forms of identity are used here.

#### machine.unique_id()

This is a unique ID embedded into the MCU chip that identifies the specific hardware chip.
On STM32 it is a true chip identifier, on ESP32 it is the Wifi MAC address.
While this unique ID has its uses they are limited by the fact that for most purposes a
system identifier, like "the orchard irrigation controller", is needed and that can easily
change as hardware is swapped out due to upgrades or failures.
The only place `machine.unique_id()` is
used in this repo is to set the MQTT `client_id` default.

#### mqtt["user"]

One of the MQTT settings that can be specified in `board_config.py` is the user ID used
to authenticate with the MQTT broker. This user ID is used in MQTT topic prefixes, specifically in
`mqrepl` because the author uses a feature of the mosquitto broker which automatically limits the
scope of MQTT topics for a user to those beginning with the user ID. E.g., by choosing a user name
"watering/orchard" (slashes are allowed in user names!) the board with that user ID is automatically
limited to only publish and subscribe to MQTT topics with the prefix "watering/orchard".

In mosquitto, rules can be added to an ACL file to allow additional topic prefixes, so this doesn't
create a hard limitation, it's just a rather simple "secure by default" option.
Nothing in this repo is dependent on this feature, however. You will just see it in the samples and
may wonder why.

#### location

The location may be thought of as the board's name. The term location was chosen because "name" is
so overused that it would be meaningless and confusing. In general, location is used in conjunction
with `mqtt["user"]` and is intended to provide a way to share a user ID across multiple
systems. For example, `mqrepl` uses topics prefixed by
`<user_id>/<location>/mqb/`, which allows multiple weather stations to share a `weather` user ID
and each one to distinguish itself by `location="orchard"`, `location="hilltop"`, etc.
If a MQTT user ID is not set then typically prefixes need to be constructed manually in the
`board_config.py`. Having a `location` is not not a hard requirement across the repo.

#### kind

In `board_config.py` `kind` should be set to a short string identifying the type of hardware used.
Currently this is only used in `board.py` to define a small number of convenience functions to
light LEDs and to measure battery voltage. It is also an often convenient variable to select
peripheral pins in projects so the same code can work e.g. on a prototype board and on a final PCB.

## Safe mode

The safe mode feature is rather elaborate and perhaps cumbersome at times. But when a board stops
responding and comes back in safe mode it's a life saver! The concept of safe mode is that very
early in the boot process (in `boot.py`) a decision is made whether it's safe to boot normally or
whether to boot into safe mode. This decision is made based on a value in RTC memory, which doesn't
get erased when the system crashes or is reset by the watchdog timer. Currently there are three
cases distinguished in `boot.py`:
- RTC memory got wiped, this is probably a cold boot (power-up), hope for the best and boot into
  normal mode.
- RTC memory has the magic value, replace that value with something bogus and boot into normal
  mode (something will need to write the magic value again so the next reset again goes to
  normal mode).
- RTC memory has a bogus value, boot into safe mode.

The key is when to write the magic value into RTC memory: it should be something that ensures that
the board has been functional for a while and was available for remote admin. The idea being that as
long as an admin can intervene and update software on the board it's OK to boot into normal mode.

One implementation of all this is provided by `watchdog.py` in the `mqrepl` directory.

The next question is what safe mode consists of. The decision made here is that it is simply
a different `sys.path`, specifically, `["/safemode", ""]`, which means that all python modules
after `boot.py` and `main.py` come from the safemode directory (having "" in the path is
required, and both `boot.py` and `main.py` must be in the root directory).

What this means is that the safemode directory can have its own version of the MQTT library, the
repl, logging, and the board config. It's not that these versions are different per-se, it's just
that they can be loaded once and then left alone while the normal versions (typ. placed into
"/lib" and "/src") can be updated and if they fail there's safe mode to ensure the board remains
reachable and the problem can be fixed.

There are a couple of issues with safemode:
- having two copies of stuff causes its own set of mistakes, it's easy to forget to eventually
  update the safemode versions after a bug fix or a password change
- there's only one version of `boot.py` and `main.py`, but hopefully they don't get changed often
- the current `sys.path` in safe mode includes the root directory, perhaps it should chdir to
  `/safemode`
- if a bug causes a hard reset (for example something causing a brief short circuit) then
  safe mode will not be triggered
- the safemode is completely decoupled from and oblivious to any OTA updates of the MicroPython
  firmware, so new firmware ends up using the same files, which means that at least the files for
  safemode need to be compatible with both firmware versions; also, the "automatic rollback" feature
  of the firmware update is decoupled from safemode (there clearly is room for improvement here...)

The safe mode check relies on RTC memory, but any memory that doesn't get erased at every reset
could be used. 
Note: on the ESP32 the safe mode relies on a fix of RTC memory!

## Component launcher in `main.py` and MQTT dispatcher in `mqtt.py`

The role of `main.py` is to start all the functional components indicated in the `board_config.py`.
It does this by looping over the python module names in `board.modules` (`board.py` has a `import *
from board_config`) and loading each one of the modules in turn. For each of the modules it calls a
`start(mqtt, config)` function passing it a handle onto the MQTT dispatcher and onto a
`board.<module_name>` dict (or an empty dict if `board` didn't contain one).

After loading all the modules the `main.py` starts the asyncio loop (when each module's start
function is called the loop is not yet running, but that doesn't prevent calling `create_task`).
Normally `main.py` never exits and the normal terminal REPL is never entered. However, a ctrl-C
breaks out of this (and at that point the asyncio loop no longer runs).
In MicroPython it is not possible to run an asyncio loop and the REPL at the same time (at least
not without a gross hack), get used to `mqboard`! ;-)

The MQTT dispatcher provides a few functions to help starting components. Specifically:
- `on_init` can register a callback that is made once when the first MQTT connection is established.
  This allows modules to delay start-up until then which is helpful to save memory for logging until
  connectivity can be established.
- `on_mqtt` can register a callback that is made each time an MQTT connection is establshed or is
  torn down. This allows modules to gate their operation based on connectivity. (Note that often the
  connection is down only very briefly.)
- `on_msg` can register a callback that is made each time an MQTT message is recevied. This is the
  primary method for receiving inbound communication. Note that each module is responsible for
  making its own subscriptions (typ. triggered by an `on_init` callback) and each callback handler
  must filter out which messages are destined for it.

Each of these callbacks uses a different type of callback: function, coroutine, and awaitable!
This is both madness and purposeful. See the comments in `mqtt.py` for details.

## Logging

It's impossible to manage remote boards without detailed information about what's hapenning and
especially about what is going wrong. After many years of working on large-scale deployments of
internet servers the author is lost without giggabytes of logs to search through and somehow he
hasn't been able to shake this habit for good and bad. The result is that everything here uses the
python standard `logging` module and produces perhaps excessive amounts of data...

The logging module provided here is an extension of the one in micropython-lib and adds logging via
MQTT. A typical use while interactively troubleshooting is to run `mqview` (from the mqboard
directory) in one terminal window/tab/pane while issuing `mqboard` commands from another
window/tab/pane.

The logging has a few quirks:
- The log lines are buffered in memory until they can be sent, this way one can often see what
  happened when connectivity faltered or before it was first established at boot! Of course this
  uses memory, so there's a max, and of course, if the cause of trouble is out-of-memory this just
  adds insult to injury!
- Each line starts with a 1-character severity, no need to waste memory on more, and then has a
  timestamp. If system time has not been set the timestamp is in milliseconds since boot. If system
  time has been set it's HH:MM:SS.sss.
- Each line is colored using ANSI escapes based on the severity, this is only done for local
  printing to the console, not for sending over MQTT. But `mqview` implements the same coloring, so
  when viewed that way the result is identical to seeing it locally.
- The amount of log messages to buffer is set in `boot.py` based on one config variable in 
  `board_config.py` and then it's reset to a different configurable value after the initial
  connection is established and the "overflow" log lines have been sent. It appears that a 10KB
  initial size is plenty to capture all boot messages and if the start-up of some modules is delayed
  using the `on_init` callback that reduces memory pressure to afford a large buffer.
- If the logging buffer overflows, the logger deletes messages by severity levels, thus hopefully
  the important stuff can be kept until it can be sent.
- Each of the `Logger` instances has its standard minimum level so debug messages can be shut up. In
  addition, there is a minimum level for sending over MQTT, actually two: one during the initial
  boot phase and one thereafter. See the `board_config_tmpl.py` file for details.

A very important note is that stdout, i.e., random stuff printed to the serial console is not
captured for sending over MQTT! The reason is that it's a bit messy. The mqrepl directory may
still have vestiges of an attempt in the abandoned `mqlogger.py` which could certainly be revived.

What happened is that the somewaht frustrated author decided to try without hooking stdout and
hasn't looked back since.
The only things that will be missed at some point are the wifi status messages printed by ESP-IDF,
but probably the best would be to hook the ESP-IDF logger and capture these that way.

## Boot process

In recap, the boot process is roughly as follows:

The overall boot process is as follows:

1. `boot.py` is always loaded by MicroPython.
   1. it first decides on normal boot vs safe mode
   2. it then starts the watchdog with an initial 70 second timeout
   3. it configures logging to buffer messages for sending later
   4. it logs some boot info, such as partition and reset cause
2. `main.py` is then loaded by MicroPython unless the raw REPL is being entered (e.g. when using
   `pyboard`) or the user hits ctrl-C early on.
   1. it prints a hello-world message with firmware and board info
   2. it configures the `sys.path` according to config
   3. it loads the modules listed in `board.modules` and calls their start functions
   4. it starts the asyncio loop
