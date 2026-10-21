# Student Name: Tahzeeb Ahmed
# Student FAN:  ahme0423
# File:         gtfs_position_collection/keep_awake.py
# Date:         21-10-2026
# Description:  Stops the computer sleeping while the collector runs (macOS, Windows, Linux).
# Usage:        from gtfs_position_collection.keep_awake import prevent_sleep
"""Stops the computer sleeping while the collector runs (macOS, Windows, Linux).

A sleeping computer misses the next collection window without any error, so
the collector holds a "no idle sleep" request for as long as it runs:
  - macOS: `caffeinate -i -s -w <pid>`, which ends by itself when the collector does;
  - Windows: SetThreadExecutionState, released by Windows when the process ends;
  - Linux: `systemd-inhibit ... sleep infinity`, stopped when the collector exits.
The display may still turn off. Closing a laptop lid sleeps it regardless.
"""

import atexit
import os
import shutil
import subprocess
import sys
import time

# SetThreadExecutionState flags: keep the request until changed; system must stay on.
ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001


def start_inhibitor(command):
    """Starts a helper process that blocks sleep; returns it, or None if it exited at once."""
    process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.5)  # A refused request (e.g. no permission) exits straight away.
    if process.poll() is not None:
        return None
    atexit.register(process.terminate)
    return process


def prevent_sleep():
    """Asks the operating system not to sleep while this process runs.

    Returns:
        A short description of how sleep is blocked, for the log, or None if
        it could not be blocked (the collector still runs; check the power
        settings by hand).
    """
    if sys.platform == "darwin" and shutil.which("caffeinate"):
        command = ["caffeinate", "-i", "-s", "-w", str(os.getpid())]
        return "caffeinate" if start_inhibitor(command) else None
    if sys.platform == "win32":
        import ctypes
        if ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED):
            return "SetThreadExecutionState"
        return None
    if sys.platform.startswith("linux") and shutil.which("systemd-inhibit"):
        command = ["systemd-inhibit", "--what=idle:sleep", "--who=gtfs collector",
                   "--why=collecting live bus positions", "--mode=block", "sleep", "infinity"]
        return "systemd-inhibit" if start_inhibitor(command) else None
    return None
