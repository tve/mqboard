import gc
print("GC threshold:", "OK" if gc.threshold() > 0 else "OOPS")

import os
print("CWD:", "OK" if os.getcwd() == "/safemode" else "OOPS")

print("connect_wifi:", "OK" if "connect_wifi" in globals() else "OOPS")

import machine
machine.reset()
