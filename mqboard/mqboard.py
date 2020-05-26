#! /usr/bin/env python3
# MQBoard - Command-line tool to manage remote MicroPython boards via MQTT
# mqboard.py - mqboard command itself
# Copyright © 2020 by Thorsten von Eicken.

import os
import click
import engine
from functools import update_wrapper


def global_opts(f):
    @click.option(
        "--server",
        "-s",
        envvar="MQBOARD_SERVER",
        required=False,
        default="localhost",
        help="MQTT server hostname or IP address.",
        metavar="SERVER",
        show_default=True,
        show_envvar=True,
    )
    @click.option(
        "--port",
        "-p",
        envvar="MQBOARD_PORT",
        required=False,
        type=click.INT,
        help="MQTT server port, default 1883 (non-TLS) or 8883 (TLS).",
        metavar="PORT",
        show_envvar=True,
    )
    @click.option(
        "--tls/--no-tls",
        envvar="MQBOARD_TLS",
        required=False,
        default=False,
        help="enable TLS.",
        metavar="PSK",
        show_default=True,
        show_envvar=True,
    )
    @click.option(
        "--timeout",
        "-T",
        envvar="MQBOARD_TIMEOUT",
        required=False,
        default="60",
        help="Timeout when waiting for a reply.",
        metavar="TIMEOUT",
        show_default=True,
        show_envvar=True,
    )
    @click.option(
        "--verbose/--quiet",
        "-v/-q",
        envvar="MQBOARD_VERBOSE",
        required=False,
        default=False,
        help="Print verbose progress information to stderr.",
        metavar="VERBOSE",
        show_default=True,
        show_envvar=True,
    )
    @click.option(
        "--prefix",
        "-p",
        envvar="MQBOARD_PREFIX",
        required=False,
        type=click.STRING,
        help="MQTT topic prefix (just before '/mqb/cmd', etc.).",
        metavar="PREFIX",
        show_default=True,
        show_envvar=True,
    )
    @click.option(
        "--topic",
        "-t",
        envvar="MQBOARD_TOPIC",
        required=False,
        type=click.STRING,
        help="MQTT topic (just before '/cmd', '/out', '/err').",
        metavar="TOPIC",
        show_default=True,
        show_envvar=True,
    )
    # @click.version_option()
    def new_func(*args, **kwargs):
        return f(*args, **kwargs)

    return update_wrapper(new_func, f)


# get_topic figures out the topic given prefix and topic options
def get_topic(prefix, topic):
    if not topic or topic == "":
        if not prefix or prefix == "":
            topic = None  # an error will be raised when engine is asked to connect
        else:
            topic = prefix + "/mqb"
    return topic


@click.group()
@global_opts
@click.pass_context
def cli(ctx, server, port, tls, timeout, verbose, prefix, topic):
    """mqboard - MQTT MicroPython Tool

    Mqboard controls MicroPython boards over MQTT. It can manipulate files on
    the board's internal filesystem, run python commands, or perform an OTA
    upgrade of micropython.

    For help on individual commands use mqboard <cmd> --help.
    """
    ctx.ensure_object(dict)
    topic = get_topic(prefix, topic)
    ctx.obj["engine"] = engine.MQTT(server, port, tls, topic, timeout, verbose)


if __name__ == "__main__":
    for fn in os.listdir(os.path.dirname(os.path.realpath(__file__))):
        if fn in ["mqboard.py", "setup.py"] or not fn.endswith(".py"):
            continue
        mod = __import__(fn[:-3])
        for name in dir(mod):
            if name.startswith("_"):
                continue
            f = getattr(mod, name)
            if isinstance(f, click.core.Command):
                cli.add_command(f, name)
    cli(obj={})
