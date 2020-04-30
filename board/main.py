# main.py - launch asyncio loop if a main is specified and if it didn't just crash

import gc
def gc_collect():
    return
    m0 = gc.mem_free()
    gc.collect()
    m1 = gc.mem_free()
    if m1-m0 > 1024:
        print("GC: {}kB freed, {}kB avail".format((m1-m0)>>10, m1>>10))

import board, logging, mqtt_async, time, micropython

print("\n===== esp32 mqttrepl at `{}` starting at {} =====\n".format(board.location, time.time()))

if hasattr(board, 'tasks') and board.tasks:
    import mqrepl, uasyncio as asyncio
    loop = asyncio.get_event_loop()
    mqr = mqrepl.MQRepl(board.config)
    mqclient = mqr.mqclient
    gc_collect()
    for t in board.tasks:
        try:
            print("-- Launching {}.{}".format(t[0],t[1]))
            mod = __import__(t[0])
            fun = getattr(mod, t[1])
            loop.create_task(fun(mqclient))
            gc_collect()
        except Exception as e:
            print("Cannot launch", t, ":")
            sys.print_exception(e)
    #logging.basicConfig(level=logging.INFO)
    #ll=logging;ll._level_dict={ll.CRITICAL:'C',ll.ERROR:'E',ll.WARNING:'W',ll.INFO:'I',ll.DEBUG:'D'}
    micropython.mem_info()
    #gc.threshold(4096)
    print("-- Launching MQRepl")
    asyncio.run(mqr.run())
