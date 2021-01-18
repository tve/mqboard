#! /usr/bin/env python3
# Copyright © 2020 by Thorsten von Eicken.

import hashlib
from pprint import pprint
from glob import glob
import click
import dirops
from pathlib import Path
import subprocess

# how to invoke mpy-cross, can be changed in spec using "mpy-cross: <mpy_cross path> <options...>"
mpy_cross = ["mpy-cross", "-march=xtensawin"]


def file_hash(fn):
    sha = hashlib.sha1()
    with open(fn, "rb") as f:
        while True:
            buf = f.read(4096)
            if len(buf) == 0:
                return sha.hexdigest()
            sha.update(buf)


# parse_spec parses the input read from fd (which must have a readline method) and return the spec
def parse_spec(infile):
    spec = {}
    lnum = 0
    tgt_dir = None
    tgt_opts = {}
    for line in infile:
        lnum += 1
        comment = line.find("#")
        if comment >= 0:
            line = line[:comment]
        line = line.rstrip()
        if line == "":
            continue
        if line[0].isspace():
            if not tgt_dir:
                raise ValueError("line %d: no target directory set" % lnum)
            tok = line.split()
            if len(tok) == 0:
                raise ValueError("line %d: expected src dir, colon, and source files" % lnum)
            src_dir = "."
            if tok[0].endswith(":"):
                src_dir = tok[0][:-1].rstrip()
                del tok[0]
            if not src_dir.endswith("/"):
                src_dir += "/"
            for t in tok:
                if tgt_dir not in spec:
                    spec[tgt_dir] = {"files": []}
                sep = t.find("->")
                if sep > 0:
                    src_file = t[:sep]
                    dst_file = t[sep + 2 :]
                    if "*" in src_file or "?" in src_file:
                        raise ValueError("Cannot mix wildcards with '->' in %s" % src_file)
                else:
                    src_file = dst_file = t
                spec[tgt_dir]["files"].append((src_dir + src_file, dst_file, tgt_opts))
        else:
            tok = line.split()
            if len(tok) == 0 or not tok[0].endswith(":"):
                raise ValueError("line %d: expected target directory followed by colon" % lnum)
            tgt_dir = tok.pop(0)[:-1].rstrip()
            if tgt_dir == "mpy-cross":  # hack!
                global mpy_cross
                mpy_cross = tok
                continue
            tgt_opts = {}
            for t in tok:
                if t == "--check-only":
                    tgt_opts["check-only"] = True
                elif t == "--no-update":
                    tgt_opts["no-update"] = True
                elif t == "--mpy":
                    tgt_opts["mpy"] = True
                else:
                    click.echo(f"unrecognized option: {t}")
    return spec


# get_actions returns a list of actions to take to bring the target dir up to date.
# It executes remote commands to retrieve SHA1 hashes and also generates local SHA1 hashes.
def get_actions(engine, dir, src):
    actions = []
    # print("Target directory", dir)
    # invoke ls command to get SHA1's of files on the board
    try:
        result = dirops.do_ls(engine, directory=dir, recursive=False, sha=True)
        result = result.decode("utf-8")
        tgt_files = eval("{" + result.replace("\n", ",") + "}")
        # print("files:", repr(tgt_files))
    except click.Abort:
        # assume this is because dir doesn't exist
        actions.append(("mkdir", dir))
        tgt_files = {}

    # Expand wildcards in source files
    src_files = []
    for src_file, tgt_file, tgt_opts in src["files"]:
        if "*" in src_file or "?" in src_file:
            src_files += [(f, f, tgt_opts) for f in glob(src_file)]
        else:
            src_files.append((src_file, tgt_file, tgt_opts))

    # Compare SHA1's and construct the actions
    for src_file, tgt_file, tgt_opts in src_files:
        if "/" in tgt_file:
            tgt_file = tgt_file[tgt_file.rindex("/") + 1 :]
        if tgt_opts.get("mpy", False) and tgt_file.endswith(".py"):
            tgt_file = tgt_file[:-3] + ".mpy"
        #print("Evaluating", src_file, "->", tgt_file)
        # if this is a .py -> .mpy transfer, make sure we've got the mpy locally
        if src_file.endswith(".py") and tgt_file.endswith(".mpy"):
            mpy_file = ".mpy/" + tgt_file
            mpy_path = Path(mpy_file)
            mpy_path.parent.mkdir(exist_ok=True)
            if not mpy_path.is_file() or Path(src_file).stat().st_mtime > mpy_path.stat().st_mtime:
                subprocess.run(mpy_cross + ["-o", mpy_file, src_file])
            src_file = mpy_file
        # now..
        why = "missing"
        if tgt_file in tgt_files:
            try:
                src_sha1 = file_hash(src_file)
            except OSError as e:
                raise click.ClickException(e)
            if src_sha1 == tgt_files[tgt_file]:
                actions.append(("ok", tgt_file))
                continue
            why = "shadiff"
            # print("  SHA MISMATCH src=%s dst=%s" % (src_sha1, tgt_files[tgt_file]))
        tgt_file = dir + ("/" if not dir.endswith("/") else "") + tgt_file
        # print("  %s %s -> %s" % (why, src_file, tgt_file))
        if tgt_opts.get("check-only", False):
            actions.append(("skip", src_file, tgt_file, why))
        elif tgt_opts.get("no-update", False) and why == "shadiff":
            actions.append(("skip", src_file, tgt_file, why))
        else:
            actions.append(("put", src_file, tgt_file, why))

    return actions


# for dir, src in spec.items():
@click.command()
@click.argument("spec", type=click.File("r"), metavar="SPEC_FILE")
@click.option(
    "--dry-run", "-n", is_flag=True, help="Dry-run: print actions without performing them."
)
@click.pass_context
def sync(ctx, spec, dry_run):
    """Synchronize files according to a specification."""
    engine = ctx.obj["engine"]
    do_sync(engine, spec, dry_run)


def do_sync(engine, spec, dry_run):
    spec = parse_spec(spec)
    # pprint(spec)

    for dir, src in spec.items():
        click.echo(f"Target directory {dir}")
        actions = get_actions(engine, dir, src)
        for a in actions:
            if a[0] == "mkdir":
                click.echo(f"  mkdir {a[1]}")
                if not dry_run:
                    dirops.do_mkdir(engine, a[1], ignore=True, path=True)
            elif a[0] == "put":
                click.echo(f"  put  {a[3]:7} {a[1]} -> {a[2]}")
                if not dry_run:
                    contents = open(a[1], "rb").read()
                    engine.perform("cmd/put", contents, tail=a[2])
            elif a[0] == "skip":
                click.echo(f"  skip {a[3]:7} {a[1]} -> {a[2]}")
            elif a[0] == "ok":
                click.echo(f"  ok   {a[1]}")
