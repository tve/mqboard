#! /usr/bin/env python3
# dir.py - MQBoard directory commands systhesized using eval
# Copyright © 2020 by Thorsten von Eicken.

import click

# ========== mkdir ==========
@click.command()
@click.option("--ignore", "-i", is_flag=True, help="Ignore if the directory already exists.")
@click.option(
    "--path", "-p", is_flag=True, help="Create intermediate directories in path, implies --ignore."
)
@click.argument("directory")
@click.pass_context
def mkdir(ctx, directory, ignore, path):
    """Create a directory on the board.
    """
    engine = ctx.obj["engine"]
    click.echo(do_mkdir(engine, directory, ignore, path))


def do_mkdir(engine, directory, ignore, path):
    if path:
        expression = (
            "import uos; p=''\n"
            "for d in '%s'.split('/'):\n"
            "  p += d;\n"
            "  try: uos.mkdir(p)\n"
            "  except OSError: pass\n"
            "  if not p.endswith('/'): p += '/'\n"
        ) % directory
    elif ignore:
        expression = "import uos; try: uos.mkdir('%s')\nexcept OSError: pass" % directory
    else:
        expression = "import uos; uos.mkdir('%s')" % directory
    return engine.perform("cmd/eval", expression)


# ========== ls ==========
@click.command()
@click.argument("directory", default=".")
@click.option("--recursive", "-r", is_flag=True, help="Recursively list files and directories.")
@click.option(
    "--sha", is_flag=True, help="List files with SHA1 of contents, incompatible with --recursive."
)
@click.pass_context
def ls(ctx, directory, recursive, sha):
    """List contents of a directory on the board.
    """
    engine = ctx.obj["engine"]
    click.echo(do_ls(engine, directory, recursive, sha))


def do_ls(engine, directory, recursive, sha):
    if sha:
        cmd = """
import uhashlib, ubinascii, uos
def _ls(d):
  def _file_sha(f):
    h = uhashlib.sha1()
    with open(f, "rb") as f:
      b = f.read(1024)
      while b != b"":
        h.update(b)
        b = f.read(1024)
    return str(ubinascii.hexlify(h.digest()), "utf-8")
  def _ls_dir(d):
    if d != "" and d[-1] != "/": d += "/"
    for f in uos.ilistdir(d):
      if f[1] & 0x4000: pass # _ls_dir(d + f[0])
      else: print("'%s':'%s'" % (f[0], _file_sha(d + f[0])))
  _ls_dir(d)
"""
        cmd += "_ls('%s'); del _ls\n" % directory
    elif recursive:
        cmd = (
            "import uos\n"
            "def _ls_dir(d):\n"
            "  if d != '' and d[-1] != '/': d += '/'\n"
            "  for f in uos.ilistdir(d):\n"
            "    if f[1]&0x4000: _ls_dir(d+f[0])\n"
            "    else: print('{:12} {}{}'.format(f[3],d,f[0]))\n"
            "_ls_dir('" + directory + "')\n"
            "del _ls_dir"
        )
    else:
        cmd = (
            "import uos\nfor f in uos.ilistdir('%s'):\n"
            " print('{:12} {}{}'.format(f[3]if len(f)>3 else 0,f[0],'/'if f[1]&0x4000 else ''))"
            % (directory)
        )
    return engine.perform("cmd/eval", cmd)


# ========== rm ==========
@click.command()
@click.argument("remote_file")
@click.pass_context
def rm(ctx, remote_file):
    """Remove a file from the board.
    """
    engine = ctx.obj["engine"]
    click.echo(do_rm(engine, remote_file))


def do_rm(engine, remote_file):
    expression = "import uos; uos.remove('%s')" % remote_file
    return engine.perform("cmd/eval", expression)


# ========== rmdir ==========
@click.command()
@click.argument("remote_dir")
@click.pass_context
def rmdir(ctx, remote_dir):
    """Remove an empty directory from the board.
    """
    engine = ctx.obj["engine"]
    click.echo(do_rmdir(engine, remote_dir))


def do_rmdir(engine, remote_dir):
    expression = "import uos; uos.rmdir('%s')" % remote_dir
    return engine.perform("cmd/eval", expression)
