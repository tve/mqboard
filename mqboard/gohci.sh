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

echo "---- updating board config ----"
#config='mqrepl = {"prefix" : mqtt["user"] + "/mqb/"}\nmodules=["mqrepl"]\n'
config='\nmodules=["mqtt", "mqrepl"]\n'
pyboard.py -c "with open('board_config.py', 'a') as f: f.write('$config')"

echo "---- fetching mqrepl topic ----"
out=$(timeout 15s pyboard.py -c "import machine; machine.reset()")
if ! echo "$out" | egrep -q "mqrepl: Subscribed"; then
    echo "OOPS, got:\n$out"
    exit 1
fi
export MQBOARD_TOPIC=$(echo "$out" | egrep "mqrepl: Subscribed" | sed -e "s/.* \(.*\)\/cmd.*/\1/")
echo "topic is <$MQBOARD_TOPIC>"

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
./mqboard eval "$RMDIR""rmdir('/test')" || exit 1


echo 'SUCCESS!'
