#! /usr/bin/env python3
# misc.py - MQBoard miscellaneous commands synthesized using eval
# Copyright © 2020 by Thorsten von Eicken.

import click


# ========== reset ==========
@click.command()
@click.option(
    "--safemode/--normalmode",
    "-s/-n",
    is_flag=True,
    help="Enter safe-mode loop, else normal loop",
    default=False,
    required=False,
)
@click.pass_context
def reset(ctx, safemode):
    """Reset the board
    """
    engine = ctx.obj["engine"]
    click.echo(do_reset(engine, safemode))


def do_reset(engine, safemode):
    cmd = (
        "sys.modules['watchdog'].reset(" + str(not safemode) + ")\n"
        "log.critical('Resetting via mqboard safemode=" + str(safemode) + "')\n"
    )
    return engine.perform("cmd/eval", cmd)
