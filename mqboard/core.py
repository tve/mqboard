#! /usr/bin/env python3
# core.py - MQBoard core commands implemented natively by MQRepl
# Copyright © 2020 by Thorsten von Eicken.

import os, hashlib
import click


# ========== eval ==========
@click.command()
@click.argument("expression", required=True)
@click.pass_context
def eval(ctx, expression):
    """Evaluate a Python expression on the board and return repr() of the result.
    """
    engine = ctx.obj["engine"]
    click.echo(engine.perform("cmd/eval", expression))


# ========== get ==========
@click.command()
@click.argument("remote_file")
@click.argument("local_file", type=click.File("wb"), required=False)
@click.pass_context
def get(ctx, remote_file, local_file):
    """
    Retrieve a file from the board, writing it to stdout if no local_file is
    specified.
    """
    engine = ctx.obj["engine"]
    data = engine.perform("cmd/get", "", tail=remote_file)
    if local_file is None:
        click.echo(data, nl=False)
    else:
        local_file.write(data)



# ========== put ==========
@click.command()
@click.argument("local", type=click.Path(exists=True))
@click.argument("remote", required=False)
@click.pass_context
def put(ctx, local, remote):
    """Put a file on the board. If the remote file is not specified the local filename is used.
    If the remote file ends in / the local filename is appended.
    """
    engine = ctx.obj["engine"]
    if remote is None:
        # Use the local filename if no remote filename is provided.
        remote = os.path.basename(os.path.abspath(local))
    elif remote.endswith("/"):
        # If remote ends in / it's a directory and we should append local filename
        remote += os.path.basename(os.path.abspath(local))
        click.echo(f"remote: {remote}")

    # Put the file on the board.
    with open(local, "rb") as infile:
        contents = infile.read()
        click.echo(engine.perform("cmd/put", contents, tail=remote))


# ========== ota ==========
@click.command()
@click.argument("application_bin", type=click.File("rb"))
@click.pass_context
def ota(ctx, application_bin):
    """Perform a MicroPython firmware update over-the-air.
    """
    engine = ctx.obj["engine"]

    # read the file into memory (it's "only" 1.5MB :-)
    contents = application_bin.read()
    sha = hashlib.sha256(contents).hexdigest()
    engine.perform("cmd/ota", contents, tail=sha)
