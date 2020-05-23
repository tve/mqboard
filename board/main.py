# main.py - safemode, watchdog, and modular asyncio task launcher
# Copyright © 2020 by Thorsten von Eicken.

# some of these are not used here, but they stay in the global env used by mqrepl, which is handy
import gc, sys, machine, os, time, micropython, esp32
import logging, board

# If board config defines logging_config then init logging to buffer the boot messages.
# Logging will be re-initialized once main calls it's start() function.
if hasattr(board, "logging"):
    logging.MQTTLog.init(
        minlevel=board.logging.get("boot_level", logging.INFO),
        maxsize=board.logging.get("boot_sz", 2880),
    )
log = logging.getLogger("main")  # will remain in global namespace

# print hello-world
log.warning("\n\n")
_uname = os.uname()
log.warning("MicroPython %s (%s)", _uname.release, _uname.version)
log.warning(_uname.machine)
_u = str(board.mqtt.get("user", "esp32"))
log.warning("%s %s starting at %s\n", _u, str(board.location), time.localtime())
del _u
del _uname

# log some info
log.warning("Boot partition: %s", esp32.Partition(esp32.Partition.RUNNING).info()[4])
_sf = "SAFE MODE boot "
if not "_safestate" in globals():  # this only happens in CI
    _safestate = "Test mode"
    safemode = True
elif _safestate == 2:
    _safestate = "Normal mode boot"
elif _safestate == 1:
    _safestate = _sf + "(hard reset)"
elif _safestate == 3:
    _safestate = _sf + "(normal mode failed)"
else:
    _safestate = _sf + "(no magic)"
log.warning(_safestate)
del _sf
del _safestate

# print reset cause in text form by reversing reset cause constants (yuck!)
cnum = machine.reset_cause()
for n in dir(machine):
    if n.endswith("_RESET") and getattr(machine, n) == cnum:
        log.warning("Reset cause: %s", n)
        break
else:
    log.warning("Reset cause: %s", cnum)
del cnum
del n


# main launches asyncio modules/tasks
def main():  # function keeps global namespace clean

    if not safemode and hasattr(board, "syspath"):
        sys.path[100:] = board.syspath  # sys.path += board.syspath

    if hasattr(board, "modules") and board.modules:
        from mqtt import MQTT
        from uasyncio import Loop as loop

        # global default asyncio exception handler
        def def_exception_handler(loop, context):
            log.error(context["message"])
            log.exc(
                context["exception"],
                "coro: %s; future: %s",
                context["future"].coro,
                context["future"],
            )

        loop.set_exception_handler(def_exception_handler)
        log.info("MEM free=%d contig=%d", gc.mem_free(), gc.mem_maxfree())

        for name in board.modules:
            try:
                log.info("Loading %s" % name)
                mod = __import__(name)
                fun = getattr(mod, "start", None)
                if fun:
                    config = getattr(board, name, {})
                    log.info("  config: [%s]", ", ".join(iter(config)))
                    lvl = config.pop("log", None)
                    if lvl:
                        logging.getLogger(name).setLevel(lvl)
                    fun(MQTT, config)
            except ImportError as e:
                log.error(str(e))
            except Exception as e:
                log.exc(e, "Cannot start %s: ", name)
            log.info("MEM free=%d contig=%d", gc.mem_free(), gc.mem_maxfree())
        # micropython.mem_info()
        #
        log.warning("Starting asyncio loop")
        loop.run_forever()


main()  # returns if no modules, if asyncio loop is stopped, or on ctrl-c
