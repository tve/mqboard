#! /bin/bash -e
export PYBOARD_DEVICE=${PYBOARD_DEVICE:-/dev/ttyUSB0}
export PATH=$HOME/bin:$PATH
cd $(dirname $0)
pwd

export MQBOARD_SERVER=192.168.0.14
if [[ $USER == gohci ]]; then
    export MQBOARD_TOPIC=esp32/gohci/mqb
else
    export MQBOARD_TOPIC=esp32/test/mqb
fi

echo "---- creating 8KB test file ----"
TF=/tmp/mqboard-test
date >$TF
i=0
while (( i < 200 )); do
    echo "Line " $(( i+2 )) $(date) >>$TF
    i=$(( i+1 ))
done
ls -ls $TF

echo "---- checking pyboard serial ----"
pyboard.py -c "print('hello world')" || true

echo "---- starting mqrepl ----"
pyboard.py --no-follow -c "import mqrepl; mqrepl.doit()"
echo done

echo "---- waiting for mqrepl to connect ----"
echo -n "."
while true; do
    out=$(./mqboard --timeout=2 eval '3+4' 2>/dev/null || true)
    [[ "$out" == "7" ]] && break
    echo -n "."
    sleep 1
done
echo " ready"

echo "---- deleting /test ----"
RMDIR='
import uos
def rmdir(dir):
    try:
        for f in uos.ilistdir(dir):
            if f[1] == 0x4000:
                rmdir(dir+"/"+f[0])
            else:
                uos.remove(f[0])
        if dir != "/":
            uos.rmdir(dir)
    except OSError as e:
        if e.args[0] != 2:
            print(e)
'
./mqboard exec "$RMDIR""rmdir('/test')"


