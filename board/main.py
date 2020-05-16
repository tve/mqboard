# main.py - launch asyncio loop if a main is specified and if it didn't just crash
import logging

log = logging.getLogger("main")


def def_exception_handler(loop, context):
    log.error(context["message"])
    log.exc(
        context["exception"], "coro: %s; future: %s", context["future"].coro, context["future"]
    )


#    log.exc(
#        context["exception"],
#        "%s: %s; coro: %s; future: %s",
#        context["message"],
#        context["exception"],
#        context["future"].coro,
#        context["future"],
#    )


def main():
    import os, board, time

    log.warning("=" * 80)
    uname = os.uname()
    log.warning("MicroPython %s; %s; %s", uname.release, uname.version, uname.machine)
    u = str(board.mqtt_config.get("user", "esp32"))
    log.warning("%s %s starting at %s\n", u, str(board.location), time.localtime())

    if hasattr(board, "modules") and board.modules:
        from mqtt import MQTT
        from uasyncio import Loop as loop
        import micropython

        loop.set_exception_handler(def_exception_handler)

        if not "mqtt" in board.modules:
            board.modules.insert(0, "mqtt")

        for t in board.modules:
            try:
                log.info("-- Loading %s" % t)
                mod = __import__(t)
                fun = getattr(mod, "start", None)
                if fun:
                    config = getattr(board, t + "_config", None)
                    if config:
                        log.info("   config: [%s]", ", ".join(iter(config)))
                        lvl = config.pop("log", None)
                        if lvl:
                            logging.getLogger(mod), setLevel(lvl)
                        fun(MQTT, config)
                    else:
                        fun(MQTT)
            except ImportError as e:
                log.error(str(e))
            except Exception as e:
                log.exc(e, "Cannot start %s: ", t)
        micropython.mem_info()
        #
        log.info("-- Starting asyncio loop")
        loop.run_forever()


main()
