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


def _run_result(*args, timeout=5) -> tuple[int | None, str, str]:
    """(returncode, stdout, stderr); returncode None when the tool is
    missing, timed out, or failed to launch."""
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
            return None, "", str(e)
        return result.returncode, result.stdout, result.stderr
    log.debug("%s not found", args[0])
    return None, "", f"{args[0]} not found"


def _run(*args, timeout=5) -> str:
    return _run_result(*args, timeout=timeout)[1]


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


def _split_terse(line: str) -> list[str]:
    """Split one line of `nmcli -t` output on unescaped colons (nmcli
    escapes ':' and '\\' inside field values, e.g. SSIDs)."""
    fields, current, escaped = [], [], False
    for ch in line:
        if escaped:
            current.append(ch)
            escaped = False
        elif ch == "\\":
            escaped = True
        elif ch == ":":
            fields.append("".join(current))
            current = []
        else:
            current.append(ch)
    fields.append("".join(current))
    return fields


def wifi_scan() -> list[dict] | None:
    """Discovered networks via NetworkManager, strongest first (the active
    one leads): [{"ssid", "signal" 0-100, "secured", "in_use"}]. Hidden
    SSIDs are skipped; duplicate BSSIDs of one SSID are merged. None when
    the scan itself failed (distinct from an empty neighborhood)."""
    code, out, err = _run_result(
        "nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY",
        "dev", "wifi", "list", "--rescan", "yes", timeout=30)
    if code != 0:
        log.warning("wifi scan failed: %s", (err or out).strip())
        return None
    networks: dict[str, dict] = {}
    for line in out.splitlines():
        fields = _split_terse(line.strip())
        if len(fields) < 4:
            continue
        in_use, ssid, signal, security = fields[0], fields[1], fields[2], fields[3]
        if not ssid:
            continue  # hidden network: nothing to select or type
        try:
            signal = int(signal)
        except ValueError:
            signal = 0
        entry = networks.setdefault(
            ssid, {"ssid": ssid, "signal": 0, "secured": False, "in_use": False})
        entry["signal"] = max(entry["signal"], signal)
        entry["secured"] = entry["secured"] or security not in ("", "--")
        entry["in_use"] = entry["in_use"] or in_use == "*"
    return sorted(networks.values(),
                  key=lambda n: (not n["in_use"], -n["signal"], n["ssid"]))


def wifi_connect(ssid: str, password: str | None = None) -> tuple[bool, str]:
    """Join a discovered network via NetworkManager. Returns (ok, message)
    with a short human-readable message for the settings popup. Blocks up
    to ~60 s — call from a worker thread only."""
    if password:
        # A saved profile for this SSID would win with its OLD secrets;
        # drop it so the typed password is what gets used.
        _run_result("nmcli", "connection", "delete", "id", ssid, timeout=10)
    args = ["nmcli", "dev", "wifi", "connect", ssid, "ifname", WIFI_INTERFACE]
    if password:
        args += ["password", password]
    code, out, err = _run_result(*args, timeout=60)
    if code == 0:
        log.info("wifi connected to %s", ssid)
        return True, f"Connected to {ssid}"
    text = (err or out).strip()
    low = text.lower()
    if code is None and "not found" in low:
        message = "nmcli not available"
    elif "secrets were required" in low or "802-11-wireless-security" in low:
        message = "Wrong password"
    elif "no network with ssid" in low:
        message = "Network not found"
    elif "timed out" in low:
        message = "Connection timed out"
    else:
        message = text.splitlines()[0][:80] if text else "Connection failed"
    log.warning("wifi connect to %s failed: %s", ssid, text or message)
    # nmcli creates the profile before activating; a failed one would keep
    # auto-retrying (and shadow the next attempt), so clean it up.
    _run_result("nmcli", "connection", "delete", "id", ssid, timeout=10)
    return False, message


def set_pairing(enabled: bool) -> None:
    """Pairing mode = adapter discoverable + pairable, so a host that forgot
    the pedal can find it again and re-pair."""
    word = "on" if enabled else "off"
    for command in ("discoverable", "pairable"):
        _run("bluetoothctl", command, word)
    log.info("pairing mode set %s", word)
