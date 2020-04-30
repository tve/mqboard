#! /bin/bash
export PYBOARD_DEVICE=${PYBOARD_DEVICE:-/dev/ttyUSB0}
export PATH=$HOME/bin:$PATH
cd $(dirname $0)
pwd

export MQBOARD_SERVER=192.168.0.14

echo "---- creating 8KB test file ----"
TF=/tmp/mqboard-test
date >$TF
i=0
while (( i < 200 )); do
    echo "Line " $(( i+2 )) $(date) >>$TF
    i=$(( i+1 ))
done
ls -ls $TF

echo "---- installing files ----"
pyboard.py -f cp ../mqrepl/mqrepl.py ../mqtt_async/mqtt_async.py :

echo "---- fetching topic ----"
out=$(pyboard.py -c "import mqrepl; print(mqrepl.TOPIC)")
export MQBOARD_TOPIC=${out%/*}
echo "topic is <$MQBOARD_TOPIC>"
[[ -n "$MQBOARD_TOPIC" ]] || exit 1

echo "---- starting mqrepl ----"
pyboard.py --no-follow -c "import mqrepl; mqrepl.doit()"
echo done

echo "---- waiting for mqrepl to connect ----"
echo -n "."
for i in 1 2 3 4 5 6; do
    out=$(./mqboard --timeout=2 eval '3+4' 2>/tmp/gohci-$$)
    [[ "$out" == "7" ]] && break
    #cat /tmp/gohci-$$
    if (( i == 6 )); then
        echo "failed, got: $out"
        cat /tmp/gohci-$$
        rm /tmp/gohci-$$
        exit 1
    fi
    echo -n "."
    sleep 1
done
rm /tmp/gohci-$$
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
./mqboard exec "$RMDIR""rmdir('/test')" || exit 1


echo 'SUCCESS!'
