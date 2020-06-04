#! /usr/bin/env python3
# misc.py - MQBoard miscellaneous commands synthesized using eval
# Copyright © 2020 by Thorsten von Eicken.

import click


# ========== reset ==========
@click.command()
@click.option(
    "--safemode",
    "-f",
    "mode",
    flag_value="safe",
    help="Full reset into safe mode",
    default=False,
    required=False,
)
@click.option(
    "--normal",
    "-n",
    "mode",
    flag_value="normal",
    help="Full reset into normal mode",
    default=True,
    required=False,
)
@click.option(
    "--soft", "-s", "mode", flag_value="soft", help="Soft reset", default=False, required=False,
)
@click.option(
    "--hard",
    "mode",
    flag_value="hard",
    help="Full reset using machine.reset(), no ACK, no log message, mqboard will hang",
    default=True,
    required=False,
)
@click.pass_context
def reset(ctx, mode):
    """Reset the board
    """
    engine = ctx.obj["engine"]
    click.echo(do_reset(engine, mode))


# send a reset, mode should be in ["normal", "safe", "soft"]
def do_reset(engine, mode):
    cmds = {
        "normal": (
            "log.critical('Resetting via mqboard into normal mode')\n"
            "sys.modules['watchdog'].reset('n')\n"
        ),
        "safe": (
            "log.critical('Resetting via mqboard into safe mode')\n"
            "sys.modules['watchdog'].reset('f')\n"
        ),
        "soft": (
            "log.critical('Soft-reset via mqboard')\n"
            "sys.modules['watchdog'].reset('s')\n"
        ),
        "hard": "machine.reset()",
    }
    cmd = cmds[mode]
    return engine.perform("cmd/eval", cmd)
