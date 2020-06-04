# boot.py - handle safemode, start the watchdog and logging
# Copyright © 2020 by Thorsten von Eicken.

import gc, sys, machine, os, uctypes, stm, pyb

# set a GC threshold early on to reduce heap fragmentation woes
gc.threshold(4096)

# chdir to / to make pybd look like esp32 (ouch!)
os.umount("/flash")
os.mount(pyb.Flash(start=0), "/")
os.chdir("/")
sys.path[:] = ["", "/lib"]

# BkpRAM class copied from https://github.com/peterhinch/micropython-micropower/blob/master/upower.py
# Copyright 2016 Peter Hinch
# This code is released under the MIT licence
class BkpRAM(object):
    BKPSRAM = 0x40024000

    def __init__(self):
        stm.mem32[stm.RCC + stm.RCC_APB1ENR] |= 0x10000000  # PWREN bit
        stm.mem32[
            stm.PWR + stm.PWR_CR
        ] |= 0x100  # Set the DBP bit in the PWR power control register
        stm.mem32[stm.RCC + stm.RCC_AHB1ENR] |= 0x40000  # enable BKPSRAMEN
        stm.mem32[stm.PWR + stm.PWR_CSR] |= 0x200  # BRE backup register enable bit
        self._ba = uctypes.bytearray_at(self.BKPSRAM, 4096)

    def idxcheck(self, idx):
        bounds(idx, 0, 0x3FF, "RTC backup RAM index out of range")

    def __getitem__(self, idx):
        self.idxcheck(idx)
        return stm.mem32[self.BKPSRAM + idx * 4]

    def __setitem__(self, idx, val):
        self.idxcheck(idx)
        stm.mem32[self.BKPSRAM + idx * 4] = val

    @property
    def ba(self):
        return self._ba  # Access as bytearray


safemode = machine.reset_cause() == machine.WDT_RESET  # unsatisfactory!
_safestate = 2 if not safemode else 4
if safemode:
    sys.path[:] = ["/safemode", ""]
    os.chdir("/safemode")  # required to get main.py from /safemode, sigh
# print("safestate:", _safestate, "safemode:", safemode, "cwd:", os.getcwd())

# watchdog
#
# The watchdog implementation is split into two parts: here the timer is armed and it's the problem
# of some module loaded later on to keep it fed.
# watchdog task has about one minute to start and change timeout
# machine.WDT(32000)

# Import logging and board; the except clause gets triggered on a fresh board when only the
# safemode directory is populated and it shortens the time to the WDT timeout to do a soft reset
try:
    import logging, board
    # import pyb
    # pyb.fault_debug(True)
    # print("fault_debug enabled")
except ImportError as e:
    sys.print_exception(e)
    if not safemode:
        # could just reset, but that causes issues if pyboard.py is used to get into raw repl
        safemode = True
        _safestate = 3
        sys.path[:] = ["/safemode", ""]
        os.chdir("/safemode")
        print("Switching to SAFE MODE")
        import logging, board

# convenience for interactive use and CI tests to bring up wifi
if hasattr(board, "connect_wifi"):
    connect_wifi = board.connect_wifi

# make __main__ globals accessible for exec/eval purposes
def GLOBALS():
    return globals()
