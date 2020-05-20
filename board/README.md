Micropython board configuration and task loader
===============================================

This directory contains `boot.py`, `main.py` and associated files to initialize a board
so it can run an `asyncio` main loop with MQTT and automatically load a number of
functional components (mqtt repl, watchdog, sntp, application, etc).

## Board configuration

__All files should be common to all boards except for one.__

The intent is that boards can be initialized easily because files with code can just be updated and
do not need to be tweaked for each board. There is only one file which is board-specific and that
does not contain any real code, just settings. This also makes it easy to maintain a public git
repository because everything but this one file can be made public without worrying about
information leakage.

Specifically, everything in this repo is common to all boards, except for the `board_config.py`
file, which is missing, and for which a template is provided in `board_config_tmpl.py`.

## Launching asyncio tasks

__All functional components are listed in `board_config.py` and started via `module.start()`__

The way a board is told which components to run is by listing them in `board_config.py` and
by forcing a convention, which is that each component consists of a python module that exposes
a module-level `start()` function that starts all activities of the module.

The start function is passed a handle onto an `MQTT` object that provides access to the
MQTT client and that supports registration of callbacks. The start function is expected to
instantiate objects used by the components and to create asyncio tasks as necessary.

## Component independence

__Functional components should not depend on the board configuration machinery__

By exposing a `start` function that is passed a handle onto MQTT and onto a config variable
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
system, like "the orchard irrigation controller", is needed and that can easily change as
hardware is swapped out due to upgrades or failures. The only place `machine.unique_id()` is
used in this repo is to set the MQTT client_id default.

#### mqtt_config["user"]

One of the MQTT settings that can be specified in `board_config.py` is the user ID used
to authenticate with the MQTT broker. This user ID is used in MQTT topic prefixes, specifically in
`mqrepl` because the author uses a feature of the mosquitto broker which automatically limits the
scope of MQTT topics for a user to those beginning with the user ID. E.g., by choosing a user name
"orchard/watering" (slashes are allowed in user names!) the board with that user ID is automatically
limited to only publish and subscribe to MQTT topics with the prefix "orchard/watering". In
mosquitto rules can be added to an ACL file to allow additional topic prefixes, so this doesn't
create a hard limitation, it's just a rather simple "secure by default" option.

#### location

The location may be thought of as the board's name. The term location was chosen because "name" is
so overused that it would be meaningless and confusing. In general, location is used in conjunction
with `mqtt_config["user"]` and is intended to provide a way to share a user ID across multiple
systems. For example, `mqrepl` uses topics prefixed by
`<user_id>/<location>/mqb/`, which allows multiple weather stations to share a `weather` user ID
and each one to distinguish itself by `location="orchard"`, `location="hilltop"`, etc.
If a MQTT user ID is not set then typically prefixes need to constructed manually in the
`board_config.py`, having a `location` is not not a hard-requirement across the repo.

#### kind

In `board_config.py` `kind` should be set to a short string identifying the type of hardware used.
Currently this is only used in `board.py` to define a small number of convenience functions to
light LEDs and to measure battery voltage. It is also an often convenient variable to select
peripheral pins in projects so the same code can work e.g. on a prototype board and on a final PCB.

## Safe mode

The safe mode check relies on RTC memory, but any memory that doesn't get erased at every reset
could be used. It detects 3 states: memory is uninitialized, happens at power-up or on external
HW reset on the ESP32

Note: the safe mode relies on an ESP32 fix of RTC memory!

## Boot process

The overall boot process is as follows:

1. `boot.py` is always loaded by MicroPython, it sets up the source search path to include `/`,
   `/lib`, and `/src`. The intent is to place non-project files (that don't change often) into
   `/lib` and project files (that get updated during dev) into `/src` to make it easier to
   update or erase all project files.
2. `boot.py` also loads `board.py` and that loads `board_config.py`, thereby bringing in
   board-specific configuration.
3. Next, `boot.py` starts the watchdog timer if `wdt_timeout` is configured in `board_config.py`.
   This is done here so the rest of the boot process is watched by the WDT.
4. Finally, `boot.py` prints the reset cause for troubleshooting purposes.
5. After `boot.py` MicroPython loads `main.py` unless an error occurred, ctrl-C is hit, or this is a
   reboot into the raw mode used by pyboard.
6. The principal role of main is to load the application.  This happens only if `modules` is 
   defined in `board_config.py`. The first step is to instantiate an `mqtt_async.MQTTClient`
   instance and register it in the `MQTT` object.
7. The main loop in main iterates over the `modules`, which is expected to be an array of
   python module names. Each module is loaded, and if it provides a `start` function then
   that is called with the `MQTT` object as argument.
8. Furthermore, if `board_config.py` defines a variable `<module>_config` then that is also
   passed to `start` making it convenient to pass in board-specific configuration details.
   (Modules can instead `import board` and thereby access anything in `board` or `board_config`,
   but passing the argument decouples modules from the board/board_config machinery.)
9. The `start()` functions are expected to perform several tasks. The instatiate any objects
   necessary for the component, they register any MQTT callbacks using the `MQTT` object,
   and they call `asyncio.Loop.create_task()` to create the tasks needed by the component
   (note that the tasks don't actually start running yet since the asyncio loop is not yet
   running).
9. Finally, `main.py` calls the asyncio loop's `run_forever()`, which then actually runs
   any tasks created by the various modules' `start` function. This means that MicroPython does not
   drop into the REPL! In general, it is not currently possible to run the REPL and an asyncio loop
   concurrently.
