import board
board.modules = ["missing_module", "module1", "module2", "module3"]



# with open("mqtt.py", "w") as f:
#    f.write("class MQTT:\n"
#            "\tdef start(clean):\n"
#            "\t\tassert clean is not None \n")

# test module without config
with open("module1.py", "w") as f:
    f.write(
        "def start(mqtt, config):\n"
        "\tassert mqtt, 'OOPS:'+str(mqtt)\n"
        "\tassert config == {}, 'OOPS:'+str(mqtt)\n"
        "\tprint('module1 OK')\n"
    )

# test module with config
board.module2 = {"foo": 1, "bar": 2}
with open("module2.py", "w") as f:
    f.write(
        "def start(mqtt,config):\n"
        "\tassert mqtt, 'OOPS:'+str(mqtt)\n"
        "\tassert 'foo' in config, 'OOPS:'+str(config)\n"
        "\tassert config['bar'] == 2, 'OOPS:'+str(config['bar'])\n"
        "\tprint('module2 OK')\n"
    )

# test module with bad start() resulting in an exception
with open("module3.py", "w") as f:
    f.write("def start(): print('OOPS')\n")

import main

main.main()
