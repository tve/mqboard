MQBOARD -- CLI Tool for MicroPython MQTT Repl
=============================================

This directory contains command-line tools to control MicroPython boards remotely.

To use these commands it is really helpful to set the `MQBOARD_SERVER` environment
variable to the address of the MQTT broker, and often to also set the
`MQBOARD_PREFIX` environment variable for the board being worked on (although it's easy
to forget that and then later run a command on the wrong board!).

mqboard
-------

`mqboard` can manipulate files on a remote board's internal filesystem, run python commands,
view logs, and perform an OTA upgrade of micropython.
Please use `mqboard --help` for documentation on the commands and options.
The current set of commands is:
```
  eval   Evaluate a Python expression on the board and return repr() of the...
  get    Retrieve a file from the board, writing it to stdout if no...
  ls     List contents of a directory on the board.
  mkdir  Create a directory on the board.
  ota    Perform a MicroPython firmware update over-the-air.
  put    Put a file on the board.
  reset  Reset the board
  rm     Remove a file from the board.
  rmdir  Remove an empty directory from the board.
  sync   Synchronize files according to a specification.
  view   View log messages.
```

The eval, put, get, and ota commands are supported natively by MQRepl, the other commands are
synthesized using eval. The reset command requires helper functions in the mqrepl watchdog.

`mqboard` does not have a command to run a script like `pyboard.py script.py`.
For dev and test it is recommended to use a USB connection, not MQTT.
To run a one-off script, for example to retrieve some data, it is recommended to put the script
and then to use eval to import it and run functions.

`mqboard` does not have an interactive mode.
This is in part because it is not currently possible to interact with the actual REPL on the
remote board.
It is also because implementing such a feature seems to add quite some code by the time it
"really works" and it doesn't seem to be that appropriate for remote management where
spontaneus commands can loose a board.

### Eval

The __eval__ command first tries to compile and `repr(eval(input_string))` the python string
provided and if that fails, it performs an `exec()` while capturing stdout. Both forms are limited
in trerms of output size: the eval by how large a message can be constructed and sent, then exec by
a pre-allocated buffer of 1400 bytes.

### OTA

The __ota__ command is rather resource intensive and sends close to 1000 messages to transfer the
firmware binary. It is recommended to first reset the board into safemode (which uses less memory)
and then perform the ota update. The `mqboard ota` command itself only writes the firmware into the
next firmware partition and marks it for booting at the next reset. One must issue such as reset
explicitly (e.g. using `mqboard reset`). Finally, after a successful reboot, the new firmware
partition must be marked as OK with ESP-IDF, which is handled by the mqrepl watchdog as part of its
"all-OK" functionality. If the reboot fails and doesn't mark the partition as OK the next reboot
will revert to the previous firmware partition. It is thus important that the safemode files are
compatible with both the current and the new version of the firmware.

### View

The view command is a simple viewer of logs over MQTT.
It is intended to display the lines sent using the logging module and it adds the line coloring
in the same way that local serial log lines are colored.

On windows, please `pip install colorama` to get the colors.

### Sync

The sync command synchronizes the content of a board's filesystem with local files.
Please see the `mqsync` description below for details.

### Global options and environment variables

- `--server | -s | MQBOARD_SERVER`: the hostname or IP address of the MQTT broker
- `--port | -p | MQBOARD_PORT`: the port of the MQTT broker
- `--tls | MQBOARD_TLS`: use TLS
- `--timeout | -T | MQBOARD_TIMEOUT`: timeout in seconds for the operation if the board doesn't
  respond (default is 60 seconds, except for the ota command where it is 10 minutes).
- `--prefix | -p | MQBOARD_PREFIX`: sets the MQTT topic prefix to use, see below.
- `--topic | -t | MQBOARD_TOPIC`: sets the MQTT topic to use, overrides `--prefix` if both are
  provided, see below.

The `--prefix` and `--topic` options serve the same purpose, which is to address the correct board.
The `--prefix` option sets an topic prefix to which `mqboard`, `mqview`, and `mqsync` add the
conventional suffix. Specifically, a prefix of `weather/hilltop` is turned into
`weather/hilltop/mqb/cmd/<command_specifics>` by `mqboard` and into
`weather/hilltop/log` by `mqview`. The intent is that all commands use the prefix as high-level
"board address" and add the conventional suffix.

The `--topic` option in contrast can be used to set the exact topic to be used to allow mounting
the functionality to arbitrary topics (although in the case
of `mqboard` the `cmd/...`, `out/...`, `err/...` topic portions will always be added).

__TODO:__ It is not currently possible to authenticate with the MQTT server, `--user` and
`--password` options should be added...

mqsync
------

`mqsync` synchronizes the content of a board's filesystem with local files. It does not produce a
mirror image the way rsync does but rather reads a specification for which files should be put where
and then makes sure it happens.
It uses mqboard internals to inspect the board's filesystem, determine what
should be copied, and then put the files. `mqsync` determines which files need
to be updated based on a SHA1 of their content. `mqsync` cannot retrieve files.

`mqsync` and `mqboard sync` are identical, except for the placement of the `--dry-run`
commandline option. `mqboard sync` is a subcommand of mqboard and can be convenient when
interactively typing commands. `mqsync` is useful to create excutable "sync" scripts,
see the blinky example.

The specification is provided to mqsync as input and the syntax is as follows:

```
# comment
<target_directory>: [--check-only] [--no-update]
  <source_file> [<source_file> ...] # <source_file> may contain shell wildcards (* and ?)
  <source_dir>: <source_file> [<source_file> ...] # cd to <source_dir> to access files
  <source_dir>: <source_file>-><target_file> # rename file when transferring
<target_directory>:
  ...
```
In English, the spec consists of blocks, each of which defines the contents of a target directory.
For each target directory a number of lines starting with whitespace list the source files to
copy there.

The target directory can be annotated with options: "--check-only" never modifies anything and can
be helpful to notify the user if something that shouldn't be blindly updated is out of date,
"--no-put" puts the files that are missing but doesn't if their SHA differs.

The source file names may contain shell wildcards (glob).
Each line can consist of a number of source file names, or of a directory path followed by source
file names in that directory.
The `->` syntax may be used to rename files during transfer, this is not compatible with also
using wildcards.
In all cases the copied files end up in the target directory itself (i.e. specifying a source file
of `foo/bar.py` doesn't cause a subdirectory `foo` to be created for `bar.py`).

Note that mqsync does not delete any extraneous files on the target.
