# This file is executed on every boot (including wake-boot from deepsleep)

# import built-in modules, they will also be available to remote eval's/exec's
import gc, sys, machine

# set a GC threshold to reduce heap fragmentation woes
gc.threshold(4096)

# set import path to include src dir
sys.path.append("/src")

try:
    from board import connect_wifi
except ImportError:
    pass

# if board config defines boot_log then init logging to buffer the boot messages
import logging
try:
    from board import logging_config
    mqtt_logger = logging.MQTTLog(
        minlevel=logging_config.get("boot_level", logging.INFO),
        maxsize=logging_config.get("boot_sz", 2880),
    )
except ImportError:
    pass
log = logging.getLogger("main")

from esp32 import Partition as p
log.warning("Booting partition %s", p(p.RUNNING).info()[4])
del p

# if board config defines watchdog_timeout then init the WDT right here so it starts as early
# as possible and can watch over the rest of the initialization process
try:
    from board import watchdog_timeout
    if watchdog_timeout > 0:
        try:
            import watchdog

            watchdog.init(watchdog_timeout)
        except Exception as e:
            log.exc(e, "Failed to start WDT due to:")
except ImportError:
    log.warning("WDT not started")

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
