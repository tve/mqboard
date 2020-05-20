# This file is executed on every boot (including wake-boot from deepsleep)

# import built-in modules, they will also be available to remote eval's/exec's
import gc, sys, machine, os, time, micropython, esp32

# set a GC threshold early on to reduce heap fragmentation woes
gc.threshold(4096)

# safe-mode
#
# The safe mode implementation is split in two parts: the check to enter safe mode happens here so
# safe mode doesn't depend on just about anything. Managing things for the next reset happens later
# in a loaded module. The workings are described in the README.
# returns: 0=bad value; 1=RTC cleared; 2=good value
def _safemode_state():
    # get magic value from RTC memory and check it out, avoid constructing a big-int
    rtc = machine.RTC()
    m = rtc.memory()
    if len(m) < 4:
        # write RTC with magic value cleared so we enter safemode if this boot fails
        w = bytearray(4)
        rtc.memory(w)
        return 1
    elif m[3] == 0xBE and m[2] == 0xEF and m[1] == 0xF0 and m[0] == 0x0D:  # 0xBEEFF00D
        # write data back with magic value cleared
        w = bytearray(m)
        w[0] = w[1] = w[2] = w[3] = 0
        rtc.memory(w)
        return 2  # RTC has "all-good" value
    else:
        return 0  # RTC has some random value, bad news...


_safestate = 2
if True:  # set to False to disable safe-mode
    _safestate = _safemode_state()  # _normal used by logging below
    safemode = not _safestate  # stays in global namespace
    if safemode:
        sys.path[:] = ["/safemode", ""]
    # print("safestate:", _safestate, "safemode:", safemode, "syspath:", sys.path)
del _safemode_state

# watchdog
#
# The watchdog implementation is split into two parts: here the timer is armed and it's the problem
# of some module loaded later on to keep it fed.
machine.WDT(timeout=70 * 1000)  # watchdog task has one minute to start and change timeout

# Import logging and board; the except clause gets triggered on a fresh board when only the
# safemode directory is populated and it shortens the time to the WDT timeout to do a soft reset
# print("sys.path is", sys.path)
try:
    import logging
    import board  # may use logging..
except ImportError as e:
    if not safemode:
        sys.print_exception(e)
        print("Resetting into safemode")
        machine.WDT(timeout=1000)  # machine.soft_reset() doesn't work here
        time.sleep(2)
    else:
        raise

# logging
#
# If board config defines logging_config then init logging to buffer the boot messages.
# Logging will be re-initialized once main calls it's start() function.
if hasattr(board, "logging_config"):
    logging.MQTTLog.init(
        minlevel=board.logging_config.get("boot_level", logging.INFO),
        maxsize=board.logging_config.get("boot_sz", 2880),
    )
log = logging.getLogger("main")  # will remain in global namespace

# log some info
log.warning("Booting partition %s", esp32.Partition(esp32.Partition.RUNNING).info()[4])
if _safestate == 2:
    _safestate = "Normal mode boot"
elif _safestate == 1:
    _safestate = "SAFE MODE boot (hard reset)"
else:
    _safestate = "SAFE MODE boot (no magic)"
log.warning(_safestate)
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

# make __main__ globals accessible for exec/eval purposes
def GLOBALS():
    return globals()

# convenience for interactive use to bring up wifi, maybe should be removed...
if hasattr(board, "connect_wifi"):
    connect_wifi = board.connect_wifi
