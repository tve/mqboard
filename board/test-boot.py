import gc
print("GC threshold:", "OK" if gc.threshold() > 0 else "OOPS")

import sys
print("SYS path:", "OK" if "" in sys.path and "/safemode" in sys.path else "OOPS")

print("connect_wifi:", "OK" if "connect_wifi" in globals() else "OOPS")

import machine
machine.reset()
