# boot.py - handle safemode, start the watchdog and logging
# Copyright © 2020 by Thorsten von Eicken.

import gc, sys, machine, os

# set a GC threshold early on to reduce heap fragmentation woes
gc.threshold(4096)

# safe-mode
#
# The safe mode implementation is split in two parts: the check to enter safe mode happens here so
# safe mode doesn't depend on anything but boot.py. Managing things for the next reset happens
# later in a loaded module. The workings are described in the README.
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


_safestate = _safemode_state()  # _safestate is used by logging in main
safemode = not _safestate  # stays in global namespace
if safemode:
    sys.path[:] = ['/safemode', '']
    os.chdir("/safemode")  # required to get main.py from /safemode, sigh
# print("safestate:", _safestate, "safemode:", safemode, "cwd:", os.getcwd())
del _safemode_state

# watchdog
#
# The watchdog implementation is split into two parts: here the timer is armed and it's the problem
# of some module loaded later on to keep it fed.
machine.WDT(timeout=70 * 1000)  # watchdog task has about one minute to start and change timeout

# Import logging and board; the except clause gets triggered on a fresh board when only the
# safemode directory is populated and it shortens the time to the WDT timeout to do a soft reset
try:
    import logging, board
except ImportError as e:
    sys.print_exception(e)
    if not safemode:
        # could just reset, but that causes issues if pyboard.py is used to get into raw repl
        safemode = True
        _safestate = 3
        sys.path[:] = ['/safemode', '']
        os.chdir("/safemode")
        print("Switching to SAFE MODE")
        import logging, board

# convenience for interactive use and CI tests to bring up wifi
if hasattr(board, "connect_wifi"):
    connect_wifi = board.connect_wifi

# make __main__ globals accessible for exec/eval purposes
def GLOBALS():
    return globals()
