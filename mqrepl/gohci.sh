#! /bin/bash
export PYBOARD_DEVICE=${PYBOARD_DEVICE:-/dev/ttyUSB0}
export PATH=$HOME/bin:$PATH
cd $(dirname $0)
pwd

echo "---- checking pyboard serial ----"
pyboard.py -c "print('hello world')" || true

echo "---- installing files ----"
pyboard.py -f cp mqrepl.py mqwdt.py :

echo "---- running test ----"
#cat /tmp/foo
out=$(pyboard.py test_mqrepl.py)
#echo "$out"
if [[ "$out" != *"start-stop OK"*"eval command OK"* ]]; then
	echo "OOPS, got:\n$out"
	exit 1
fi
echo 'SUCCESS!'
