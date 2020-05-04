import main

try:
    main.gc_collect()
    print("gc_collect: OK")
except Exception as e:
    print("gc_collect: OOPS", e)

import board
board.modules = ["missing_module", "module1", "module2", "module3"]
board.module2_config = {"foo":1, "bar":2}
with open("mqtt.py", "w") as f:
    f.write("class MQTT:\n"
            "\tdef start(clean):\n"
            "\t\tassert(clean is not None)\n")
with open("module1.py", "w") as f:
    f.write("def start(mqtt):\n"
            "\tassert(mqtt), 'OOPS:'+str(mqtt)\n"
            "\tprint('module1 OK')\n")
with open("module2.py", "w") as f:
    f.write("def start(mqtt,config):\n"
            "\tassert mqtt, 'OOPS:'+str(mqtt)\n"
            "\tassert 'foo' in config, 'OOPS:'+str(config)\n"
            "\tassert config['bar'] == 2, 'OOPS:'+str(config['bar'])\n"
            "\tprint('module2 OK')\n")
with open("module3.py", "w") as f:
    f.write("def start(): print('OOPS')\n")
main.main()
