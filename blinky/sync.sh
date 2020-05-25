#! /bin/bash -e
../mqboard/mqboard.py "$@" sync - <<'EOF'
/lib:
  ./mpy-lib: sntp.py sysinfo.py
  ../board: logging.py board.py mqtt.py
  ../mqrepl: mqrepl.py watchdog.py
  ../mqtt_async/mqtt_async.py
/src:
  blinky.py
/:
  board_config.py
EOF
exit 0

root=$(mqboard "$@" ls 2>/dev/null)
[[ "$root" != *boot.py* ]] && echo "WARNING: /boot.py missing; use sync-safemode"
[[ "$root" != *main.py* ]] && echo "WARNING: /main.py missing; use sync-safemode"
[[ "$root" != *safemode* ]] && echo "WARNING: /safemode/ missing; use sync-safemode"
echo "Reminder: /boot.py, and /main.py were not sync'd"
