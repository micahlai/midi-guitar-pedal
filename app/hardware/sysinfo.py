"""System status readouts + pairing toggle for the on-device settings menu.

Everything shells out to standard Raspberry Pi OS tools with hard timeouts
and degrades to unknown values — the settings menu must never hang or crash
because a tool is missing. Called only from SettingsLogic's worker threads,
never from the 10 ms main event loop.
"""

import glob
import logging
import socket
import subprocess

log = logging.getLogger("controller.hardware.sysinfo")

WIFI_INTERFACE = "wlan0"


def _run(*args, timeout=5) -> str:
    # /usr/sbin (iw, iwgetid, …) isn't on PATH in every context.
    for prefix in ("", "/usr/sbin/", "/usr/bin/"):
        command = (prefix + args[0], *args[1:])
        try:
            result = subprocess.run(command, capture_output=True, text=True,
                                    stdin=subprocess.DEVNULL, timeout=timeout)
        except FileNotFoundError:
            continue
        except (OSError, subprocess.TimeoutExpired) as e:
            log.debug("%s failed: %s", args[0], e)
            return ""
        return result.stdout
    log.debug("%s not found", args[0])
    return ""


def wifi_ssid() -> str | None:
    """SSID when the Wi-Fi interface is associated, else None."""
    for line in _run("iw", "dev", WIFI_INTERFACE, "link").splitlines():
        line = line.strip()
        if line.startswith("SSID:"):
            return line[len("SSID:"):].strip()
    return None


def ip_address() -> str | None:
    addresses = _run("hostname", "-I").split()
    return addresses[0] if addresses else None


def hostname() -> str:
    return socket.gethostname()


def bluetooth_status() -> dict:
    """{"powered": bool, "discoverable": bool} from `bluetoothctl show`."""
    lines = [line.strip() for line in _run("bluetoothctl", "show").splitlines()]

    def flag(name: str) -> bool:
        return any(line.startswith(f"{name}: yes") for line in lines)

    return {"powered": flag("Powered"), "discoverable": flag("Discoverable")}


def usb_gadget_state() -> str:
    """UDC state: "configured" = USB host connected and enumerated,
    "not attached" = no host on the data port."""
    for path in glob.glob("/sys/class/udc/*/state"):
        try:
            with open(path) as f:
                return f.read().strip()
        except OSError:
            pass
    return "unknown"


def set_pairing(enabled: bool) -> None:
    """Pairing mode = adapter discoverable + pairable, so a host that forgot
    the pedal can find it again and re-pair."""
    word = "on" if enabled else "off"
    for command in ("discoverable", "pairable"):
        _run("bluetoothctl", command, word)
    log.info("pairing mode set %s", word)
