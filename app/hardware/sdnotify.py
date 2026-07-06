"""Minimal sd_notify(3) client — READY/WATCHDOG pings without dependencies.

systemd passes the notification socket in NOTIFY_SOCKET; outside systemd the
variable is unset and every call is a no-op, so main.py can ping
unconditionally.
"""

import logging
import os
import socket

log = logging.getLogger("controller.hardware.sdnotify")


def notify(message: str) -> None:
    path = os.environ.get("NOTIFY_SOCKET")
    if not path:
        return
    if path.startswith("@"):  # abstract socket namespace
        path = "\0" + path[1:]
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
            sock.connect(path)
            sock.send(message.encode())
    except OSError as e:
        log.debug("sd_notify failed: %s", e)
