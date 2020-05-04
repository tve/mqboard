# main.py - launch asyncio loop if a main is specified and if it didn't just crash

def gc_collect():
    import gc
    return
    m0 = gc.mem_free()
    gc.collect()
    m1 = gc.mem_free()
    if m1 - m0 > 1024:
        log.debug("GC: %dkB freed, %dkB avail" % ((m1 - m0) >> 10, m1 >> 10))

def main():
    import board, logging, time

    log = logging.getLogger("main")

    print("\n===== esp32 `{:s}` starting at {} =====\n".format(board.location, time.localtime()))

    if hasattr(board, "modules") and board.modules:
        from mqtt import MQTT
        from uasyncio import Loop as loop
        import micropython

        MQTT.start(False)

        for t in board.modules:
            try:
                log.info("-- Loading %s" % t)
                mod = __import__(t)
                fun = getattr(mod, "start", None)
                if fun:
                    config = getattr(board, t+"_config", None)
                    if config:
                        log.info("with config for: %s", ", ".join(iter(config)))
                        fun(MQTT, config)
                    else:
                        fun(MQTT)
            except ImportError as e:
                log.error(str(e))
            except Exception as e:
                import sys
                log.error("Cannot start %s: " % t)
                sys.print_exception(e)
        micropython.mem_info()
        # gc.threshold(4096)
        log.info("-- Starting asyncio loop")
        loop.run_forever()
main()
