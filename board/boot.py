# This file is executed on every boot (including wake-boot from deepsleep)

import gc
gc.threshold(4096)

import sys
sys.path.append("/src")

from esp32 import Partition as p
print("Booting partition", p(p.RUNNING).info()[4])

from board import connect_wifi

# if board config defines wdt_timeout then init the WDT right here so it starts as early
# as possible and can watch over the rest of the initialization process
try:
    from board import wdt_timeout
    if wdt_timeout > 0:
        try:
            import mqwdt
            mqwdt.init(board.wdt_timeout)
        except Exception as e:
            print("Failed to start WDT:")
            sys.print_exception(e)
except ImportError:
    print("WDT not started")

# print reset cause in text form by reversing reset cause constants (yuck!)
import machine
cnum = machine.reset_cause()
for n in dir(machine):
    if n.endswith("_RESET") and getattr(machine, n) == cnum:
        print("Reset cause:", n)
        break
else:
    print("Reset cause:", cnum)
del cnum
