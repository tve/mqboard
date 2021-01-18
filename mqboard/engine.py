#! /usr/bin/env python3
# MQBoard - Command Line Interface
# Copyright © 2020 by Thorsten von Eicken.

import base64, random, struct, time
import click
import paho.mqtt.client as paho

BUFLEN = 1400  # "optimal" buffer size to make mqtt message fit into TCP segment


def ticks():
    return time.monotonic()


# MQTT is the engine for performing commands over ... MQTT
class MQTT:
    def __init__(self, server, port, tls, topic, timeout, debug):
        self._server = server
        if not port:
            port = 8883 if tls else 1883
        self._port = port
        self._topic = topic
        self._timeout = int(timeout)
        self._connected = False
        self._debug = debug
        # get paho mqtt client
        client_id = "mqboard-" + MQTT._gen_id(6)
        self._mqclient = paho.Client(client_id=client_id, clean_session=True)
        # _mqclient.enable_logger(logging.getLogger("paho-mqtt"))
        if tls:
            self._mqclient.tls_set()

    def debug(self, msg):
        if self._debug:
            click.echo(msg, err=True)

    def connect(self):
        if self._connected:
            return

        if not self._topic:
            raise click.UsageError("--prefix or --topic are required")
        self.debug(f"Connecting to {self._server}:{self._port}")

        def on_conn(cli, ud, fl, rc):
            if rc != 0:
                raise click.UsageError(paho.connack_string(rc))
            self._connected = True

        def on_disconn(cli, ud, rc):
            self._connected = False

        self._mqclient.on_connect = on_conn
        self._mqclient.on_disconnect = on_disconn
        self._mqclient.connect(self._server, self._port)

    @staticmethod
    def _gen_id(nbytes):
        return str(
            base64.urlsafe_b64encode(bytes(random.sample(range(256), k=nbytes))), encoding="ascii"
        )

    # _mktopic produces the appropriate MQTT topic given the command and a possible "topic tail".
    # The tail is either a file path (put or get commands) or a SHA (ota).
    def _mktopic(self, cmd, tail=""):
        return self._topic + "/" + cmd + "/" + self._topic_id + ("/" + tail if tail else "")

    # perform does all the work to execute a command on the board. It sends the command, collects
    # the response and calls the 'cb' callback with it.
    def perform(self, cmd, msg, tail=None):
        t0 = ticks()  # times the entire command
        rcv_at = ticks()  # last received message for timeout purposes
        got_error = None  # flag to signal the end, False->OK; True->abort with raise
        sz = 0
        next_seq = 0  # next expected sequence number
        ack = -1  # ack for flow-control
        subscribed = False  # flag to pop out of loop waiting for subscription
        output = b""  # output ultimately returned from perform

        # generate an ID we can use for the MQTT topics to match replies
        self._topic_id = MQTT._gen_id(6)

        def on_reply(cli, ud, msg):
            nonlocal sz, next_seq, ack, rcv_at, output, got_error
            self.debug(f"Received reply on topic '{msg.topic}' with QoS {msg.qos}")
            # parse message header
            if len(msg.payload) < 2:
                return
            seq = ((msg.payload[0] & 0x7F) << 8) | msg.payload[1]
            last = (msg.payload[0] & 0x80) != 0
            # self.debug(f"seq={seq} last={last} payload-len={len(msg.payload)}")
            self.debug(f"msg=<{msg.payload}>")
            # check sequence number
            if seq != 0x7fff:
                if seq < next_seq:
                    self.debug(f"Duplicate message, expected seq={next_seq}, got {seq}")
                    return
                if seq > next_seq:
                    raise click.ClickException(
                        f"Missing message(s), expected seq={next_seq}, got {seq}"
                    )
                next_seq = seq + 1
            # handle ACK for long streams (a bit of a hack!)
            if len(msg.payload) - 2 < 10 and msg.payload[2:].startswith(b"SEQ "):
                try:
                    s = int(msg.payload[6:])
                    if s > ack:
                        ack = s
                        print(".", end="")
                        return
                except ValueError:
                    raise click.ClickException("Bad ACK received")
            sz += len(msg.payload) - 2
            output += msg.payload[2:]
            rcv_at = ticks()
            if last:
                dt = ticks() - t0
                self.debug(
                    "{:.3f}kB in {:.3f}s -> {:.3f}kB/s".format(sz / 1024, dt, sz / 1024 / dt)
                )
                got_error = False

        def on_error(cli, ud, message):
            nonlocal got_error
            click.echo(message.payload.strip(), err=True)
            got_error = True

        def on_sub(client, userdata, mid, granted_qos):
            nonlocal subscribed
            subscribed = True

        def loop():
            if ticks() - rcv_at > self._timeout:
                raise click.ClickException("Timeout!")
            self._mqclient.loop(0.1)

        # first connect
        self.connect()

        # subscribe to the response topics
        reply_topic = self._mktopic("reply/out")
        err_topic = self._mktopic("reply/err")
        self._mqclient.message_callback_add(reply_topic, on_reply)
        self._mqclient.message_callback_add(err_topic, on_error)
        self._mqclient.on_subscribe = on_sub
        (res, sub_mid) = self._mqclient.subscribe([(reply_topic, 1), (err_topic, 1)])
        self.debug(f"Subscribing to {reply_topic} and {err_topic}")
        if res != paho.MQTT_ERR_SUCCESS:
            raise click.ClickException("Subscribe failed")
        while not subscribed:
            loop()

        # iterate through content and send one buffer at a time
        seq = 0
        if isinstance(msg, str):
            msg = msg.encode()
        buf = bytearray(BUFLEN + 2)
        cmd_topic = self._mktopic(cmd, tail=tail)
        flowctrl = len(msg) > 100 * 1024  # hack
        while got_error is None:
            # make sure we're not more than 16 messages ahead of flow-control ACKs
            while flowctrl and seq - ack > 16 and got_error is None:
                loop()
            # construct outgoing message with 2-byte header (last flag and seq number)
            buf[2:] = msg[:BUFLEN]
            msg = msg[BUFLEN:]
            last = len(msg) == 0
            struct.pack_into("!H", buf, 0, last << 15 | seq)
            # publish
            sz += len(buf)
            self.debug(f"Pub {cmd_topic} #{seq} last={last} len={len(buf)}")
            self._mqclient.publish(cmd_topic, buf, qos=1)
            #if seq % 4 == 3:
            #    time.sleep(0.1)  # mosquitto swallows messages if we don't do this !?
            seq += 1
            loop()
            if len(msg) == 0:
                break
        # self.debug("done publishing")

        # wait for replies
        while got_error is None:
            loop()

        # wrap up
        self._mqclient.unsubscribe(reply_topic)
        self._mqclient.unsubscribe(err_topic)
        if got_error:
            raise click.Abort()
        return output
