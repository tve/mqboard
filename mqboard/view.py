#! /usr/bin/env python3
# Copyright © 2020 by Thorsten von Eicken.

import click
import paho.mqtt.client as paho


@click.command()
@click.pass_context
def view(ctx):
    """View log messages."""
    engine = ctx.obj["engine"]
    do_view(engine)


def do_view(engine):
    # gross hack to change topic, need to figure out better way
    if engine._topic and engine._topic.endswith("mqb"):
        engine._topic = engine._topic[:-3] + "log"

    subscribed = False

    def on_log(cli, ud, msg):
        m = msg.payload.decode("utf-8")
        if len(m) < 4:
            click.echo(m)
            return
        severity = m[:2]
        if severity == "C ":
            click.secho(m, fg="magenta", bold=True)
        elif severity == "E ":
            click.secho(m, fg="red", bold=True)
        elif severity == "W ":
            click.secho(m, fg="yellow", bold=True)
        elif severity == "I ":
            click.secho(m, fg="green")
        elif severity == "D ":
            click.secho(m, dim=True)
        else:
            click.echo(m)
        # pref = {"C ": 35, "E ": 31, "W ": 33, "I ": 32, "D ": 2}.get(m[:2], 0)
        # print("\033[%dm%s\033[0m" % (pref, m))

    def on_sub(client, userdata, mid, granted_qos):
        nonlocal subscribed
        subscribed = True

    # first connect
    engine.connect()

    # subscribe to the log topic
    topic = engine._topic
    engine._mqclient.message_callback_add(topic, on_log)
    engine._mqclient.on_subscribe = on_sub
    (res, sub_mid) = engine._mqclient.subscribe([(topic, 1)])
    engine.debug(f"Subscribing to {topic}")
    if res != paho.MQTT_ERR_SUCCESS:
        raise click.ClickException("Subscribe failed")
    while True:
        engine._mqclient.loop(1)
