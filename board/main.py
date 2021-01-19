# main.py - safemode, watchdog, and modular asyncio task launcher
# Copyright ©2020 by Thorsten von Eicken.

# some of these are not used here, but they stay in the global env used by mqrepl, which is handy
import gc
import sys
import machine
import os
import time
import logging
import board

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

# log some info and check any heap constraints given in the config
if sys.platform == "esp32":
    import esp32

    log.warning("Boot partition: %s", esp32.Partition(esp32.Partition.RUNNING).info()[4])

    # heap constraints, see docs https://github.com/tve/micropython/blob/esp32-set-heapsize/docs/esp32/quickref.rst#controlling-the-python-heap-size
    # FIXME: if machine.reset() gets called we end up in safeboot mode, which is not ideal
    # probably the whole thing needs to be moved out of main and be done later when the
    # watchdog can be used to reboot into the same mode
    min_idf_heap = getattr(board, "min_idf_heap", None)
    max_mp_heap = getattr(board, "max_mp_heap", None)
    if min_idf_heap or max_mp_heap:
        try:
            from esp32 import NVS, idf_heap_info
            nvs = NVS("micropython")
            reset=False
            # minimum IDF heap size
            if min_idf_heap:
                try: mih = nvs.get_i32("min_idf_heap")
                except: mih = None
                print("mih", mih, "min_idf_heap", min_idf_heap)
                if mih != min_idf_heap:
                    nvs.set_i32("min_idf_heap", min_idf_heap)
                    reset= True
            # maximum MP heap size
            if max_mp_heap:
                try: mmh = nvs.get_i32("max_mp_heap")
                except: mmh = None
                print("mmh", mmh, "max_mp_heap", max_mp_heap)
                if mmh != max_mp_heap:
                    nvs.set_i32("max_mp_heap", max_mp_heap)
                    reset= True
            # print some info
            if reset:
                log.warning("Resetting to fix heap size")
                nvs.commit()
                machine.reset()

        except Exception as e:
            log.exc(e, "No heap size control")

# log boot mode info
_sf = "Normal mode boot "
if "/safemode" in sys.path:
    _sf = "SAFE MODE boot "
if "_safestate" not in globals():  # this only happens in CI
    _safestate = "Test mode"
    safemode = True
elif _safestate == 2:
    _safestate = _sf + "(good magic)"
elif _safestate == 1:
    _safestate = _sf + "(hard reset)"
elif _safestate == 3:
    _safestate = _sf + "(normal mode failed)"
elif _safestate == 4:  # pybd
    _safestate = _sf + "(WDT)"
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
        from uasyncio import sleep_ms, Loop as loop
        from esp32 import idf_heap_info, HEAP_DATA

        # global default asyncio exception handler
        def def_exception_handler(loop, context):
            log.error("Task exception: %s", context["message"])
            log.exc(
                context["exception"],
                "coro: %s; future: %s",
                context["future"].coro.coro,
                context["future"],
            )

        def lm():
            log.info("MEM free=%d contig=%d", gc.mem_free(), gc.mem_maxfree())
            log.info("IDF %s", [h[2] for h in idf_heap_info(HEAP_DATA) if h[2] > 0])

        loop.set_exception_handler(def_exception_handler)
        lm()

        # the loader task iterates through the modules (typ from board_config) and starts each one
        async def loader():
            for name in board.modules:
                try:
                    log.info("Loading %s" % name)
                    mod = __import__(name)  # load the module by name
                    await sleep_ms(0)
                    fun = getattr(mod, "start", None)  # check whether the module has a start()
                    if fun:
                        config = getattr(board, name, {})  # check whether we got a config for this
                        log.info("  config: [%s]", ", ".join(iter(config)))
                        lvl = config.pop("log", None)
                        if lvl:
                            logging.getLogger(name).setLevel(lvl)
                        fun(MQTT, config)  # call the module's start() function
                        await sleep_ms(0)
                except ImportError as e:
                    log.error(str(e))
                except Exception as e:
                    log.exc(e, "Cannot start %s: ", name)
                lm()

        loop.create_task(loader())
        log.warning("Starting asyncio loop")
        loop.run_forever()


main()  # returns if no modules, if asyncio loop is stopped, or on ctrl-c
