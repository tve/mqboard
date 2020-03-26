# MicroPython MQTT

This repository contains libraries and tools for using MQTT on MicroPython boards, primarily on the
ESP32.

- `mqtt-async` contains an MQTT client library that uses asyncio and forms the backbone of most other
  libraries and tools here. *Beta release*
- `mqrepl` contains a library to run a REPL via MQTT, basically to be able to send filesystem and
  interactive commands to a MicroPython board via MQTT. *Work in progress*
- `mqboard` contains a python commandline tool to be run on a developer's machine to send commands
  to `mqrepl`. *Work in progress*
- `board` contains sample `boot.py`, `main.py`, etc. files to populate a board for use my `mqrepl`.
  *Work in progress*

For help, please post on https://forum.micropython.org 

Note: this repository is not a fork or a clone of Peter Hinch's Micropython-MQTT project.

For license info see the LICENSE file.
