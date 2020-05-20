# main.py - modular asyncio task launcher

# the following import is a no-op because main runs in same namespace as boot.py
# it is here anyway to make test-main.py work
import sys, os, time, board, logging
log = logging.getLogger("main")

# main launches asyncio modules/tasks
def main():  # function keeps global namespace clean
    # print hello-world
    log.warning("=" * 60)
    uname = os.uname()
    log.warning("MicroPython %s (%s)", uname.release, uname.version)
    log.warning(uname.machine)
    u = str(board.mqtt.get("user", "esp32"))
    log.warning("%s %s starting at %s\n", u, str(board.location), time.localtime())

    # safemode is set in boot.py but globals().get is used here to make test-main.py work
    if not globals().get("safemode",False) and hasattr(board, "syspath"):
        sys.path[100:] = board.syspath  # sys.path += board.syspath

    if hasattr(board, "modules") and board.modules:
        from mqtt import MQTT
        from uasyncio import Loop as loop
        import micropython

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

        for name in board.modules:
            try:
                log.info("-- Loading %s" % name)
                mod = __import__(name)
                fun = getattr(mod, "start", None)
                if fun:
                    config = getattr(board, name, {})
                    log.info("   config: [%s]", ", ".join(iter(config)))
                    lvl = config.pop("log", None)
                    if lvl:
                        logging.getLogger(name).setLevel(lvl)
                    fun(MQTT, config)
            except ImportError as e:
                log.error(str(e))
            except Exception as e:
                log.exc(e, "Cannot start %s: ", name)
        micropython.mem_info()
        #
        log.info("-- Starting asyncio loop")
        loop.run_forever()


main()  # returns if no modules, if asyncio loop is stopped, or on ctrl-c
