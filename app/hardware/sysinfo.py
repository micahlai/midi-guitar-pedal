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
import time

log = logging.getLogger("controller.hardware.sysinfo")

WIFI_INTERFACE = "wlan0"

# How long to let a requested sweep land before reading the list. The
# rescan request returns immediately; the results arrive asynchronously.
SCAN_SETTLE_SECONDS = 5.0


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


def _run_root(*args, timeout=5) -> tuple[int | None, str, str]:
    """Run a command as root (passwordless sudo, as main.py does for
    poweroff).

    NetworkManager's polkit policy authorizes scanning, connecting and
    profile edits only for an ACTIVE LOCAL SESSION. The controller is a
    session-less systemd service, so unprivileged nmcli gets "not authorized"
    — and for a scan that surfaces as an EMPTY list rather than an error,
    which reads as "no networks found". Reading a saved passphrase (`nmcli
    -s`) is privileged for the same reason. Anything that mutates NM state,
    or needs its secrets, has to go through here.
    """
    return _run_result("sudo", "-n", *args, timeout=timeout)


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


def wifi_scan(force: bool = False) -> list[dict] | None:
    """Discovered networks via NetworkManager, strongest first (the active
    one leads): [{"ssid", "signal" 0-100, "secured", "in_use"}]. Hidden
    SSIDs are skipped; duplicate BSSIDs of one SSID are merged. None when
    the scan itself failed (distinct from an empty neighborhood).

    The scan is REQUESTED as root and then waited for, rather than leaning on
    `--rescan yes`: an unprivileged rescan is refused by polkit (see
    _run_root) and nmcli then just prints its cached list. That cache decays
    to only the associated AP while connected, so the popup would show one
    network — or none — with no error anywhere. `force=False` skips the sweep
    and reads that cache deliberately (e.g. redrawing an open popup).
    """
    if force:
        code, out, err = _run_root("nmcli", "dev", "wifi", "rescan", timeout=20)
        if code != 0:
            # "Scanning already in progress" is normal; the wait below still
            # picks up whatever that in-flight sweep finds.
            log.info("rescan request: %s", (err or out).strip())
        time.sleep(SCAN_SETTLE_SECONDS)
    return _scan_once("no")


def _scan_once(rescan: str) -> list[dict] | None:
    code, out, err = _run_result(
        "nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY",
        "dev", "wifi", "list", "--rescan", rescan, timeout=30)
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


def profile_for_ssid(ssid: str) -> str | None:
    """The name of the saved profile carrying this SSID, or None.

    Matched on the profile's 802-11-wireless.ssid, NOT on its name: a profile
    is frequently not named after its network. Raspberry Pi Imager provisions
    Wi-Fi through netplan, which names it `netplan-wlan0-<SSID>` — so a
    name-based lookup misses the very network the pedal boots on.
    """
    code, out, _ = _run_result(
        "nmcli", "-t", "-f", "NAME,TYPE", "connection", "show", timeout=10)
    if code != 0:
        return None
    for line in out.splitlines():
        fields = _split_terse(line)
        if len(fields) < 2 or fields[1] != "802-11-wireless":
            continue
        name = fields[0]
        code, saved, _ = _run_result(
            "nmcli", "-g", "802-11-wireless.ssid", "connection", "show",
            "id", name, timeout=10)
        if code == 0 and saved.strip() == ssid:
            return name
    return None


def _saved_psk(name: str) -> str | None:
    """The passphrase stored on an existing profile, so a failed retype can
    be rolled back. None when it can't be read (no profile, no permission)."""
    code, out, _ = _run_root(
        "nmcli", "-s", "-g", "802-11-wireless-security.psk",
        "connection", "show", "id", name, timeout=10)
    return out.strip() if code == 0 and out.strip() else None


def _failure_message(code: int | None, text: str) -> str:
    low = text.lower()
    if code is None and "not found" in low:
        return "nmcli not available"
    if "secrets were required" in low or "802-11-wireless-security" in low:
        return "Wrong password"
    if "no network with ssid" in low:
        return "Network not found"
    if "timed out" in low:
        return "Connection timed out"
    return text.splitlines()[0][:80] if text else "Connection failed"


def wifi_connect(ssid: str, password: str | None = None) -> tuple[bool, str]:
    """Join a network via NetworkManager. Returns (ok, message) with a short
    human-readable message for the settings popup. Blocks up to ~60 s — call
    from a worker thread only.

    A profile that existed before this call is NEVER deleted, whatever
    happens: a mistyped password on the pedal must not destroy the
    credentials for the network we are reachable on. A wrong retype is rolled
    back to the stored passphrase; only a profile this call created itself is
    cleaned up on failure (a half-made one would auto-retry and shadow the
    next attempt).
    """
    existing = profile_for_ssid(ssid)  # the PROFILE NAME, which may not be the SSID
    previous_psk = _saved_psk(existing) if (existing and password) else None

    if existing and password:
        # Update the saved profile in place rather than recreating it.
        code, out, err = _run_root(
            "nmcli", "connection", "modify", "id", existing,
            "wifi-sec.psk", password, timeout=10)
        if code != 0:
            text = (err or out).strip()
            log.warning("wifi psk update for %s failed: %s", ssid, text)
            return False, _failure_message(code, text)
        code, out, err = _run_root(
            "nmcli", "connection", "up", "id", existing, timeout=60)
    elif existing:
        # No password typed: activate with the secrets already stored.
        code, out, err = _run_root(
            "nmcli", "connection", "up", "id", existing, timeout=60)
    else:
        args = ["nmcli", "dev", "wifi", "connect", ssid, "ifname", WIFI_INTERFACE]
        if password:
            args += ["password", password]
        code, out, err = _run_root(*args, timeout=60)

    if code == 0:
        log.info("wifi connected to %s", ssid)
        return True, f"Connected to {ssid}"

    text = (err or out).strip()
    message = _failure_message(code, text)
    log.warning("wifi connect to %s failed: %s", ssid, text or message)

    if existing:
        if previous_psk is not None:
            # Put the working passphrase back — the profile must survive a
            # bad retype intact.
            _run_root("nmcli", "connection", "modify", "id", existing,
                      "wifi-sec.psk", previous_psk, timeout=10)
            log.info("restored previous passphrase on %s", existing)
    else:
        # Only ours to remove: it did not exist when we started.
        _run_root("nmcli", "connection", "delete", "id", ssid, timeout=10)
    return False, message


# NetworkManager profile name for the pedal's own access point. Kept out of
# the SSID namespace so it can never collide with a scanned network.
AP_CONNECTION = "pedal-hotspot"


def ap_active() -> bool:
    """True when the pedal is currently hosting its own network."""
    code, out, _ = _run_result(
        "nmcli", "-t", "-f", "NAME", "connection", "show", "--active",
        timeout=10)
    if code != 0:
        return False
    return any(_split_terse(line)[0] == AP_CONNECTION
               for line in out.splitlines() if line.strip())


def ap_start(ssid: str, password: str) -> tuple[bool, str]:
    """Host an access point on wlan0 so a laptop can reach the web editor
    with no infrastructure network. Returns (ok, message).

    The radio is single-band and cannot be client and AP at once, so this
    drops any Wi-Fi connection — including the one an ssh session is riding
    on. The profile is created with autoconnect off: a reboot always comes
    back as a Wi-Fi client, so a bad AP can never be sticky.
    """
    if len(password) < 8:
        return False, "Password must be 8+ chars"
    _run_root("nmcli", "connection", "delete", "id", AP_CONNECTION, timeout=10)
    code, out, err = _run_root(
        "nmcli", "device", "wifi", "hotspot", "ifname", WIFI_INTERFACE,
        "con-name", AP_CONNECTION, "ssid", ssid, "password", password,
        timeout=60)
    if code != 0:
        text = (err or out).strip()
        log.warning("hotspot start failed: %s", text)
        _run_root("nmcli", "connection", "delete", "id", AP_CONNECTION,
                  timeout=10)
        return False, _failure_message(code, text) if text else "Hotspot failed"
    # Never auto-start on boot: Wi-Fi client must always win a cold start.
    _run_root("nmcli", "connection", "modify", "id", AP_CONNECTION,
              "connection.autoconnect", "no", timeout=10)
    log.info("hotspot up: %s", ssid)
    return True, f"Hosting {ssid}"


def ap_stop() -> tuple[bool, str]:
    """Tear the access point down and hand wlan0 back to NetworkManager,
    which reconnects to the best saved network (the AP is autoconnect=no)."""
    code, out, err = _run_root(
        "nmcli", "connection", "down", "id", AP_CONNECTION, timeout=30)
    _run_root("nmcli", "connection", "delete", "id", AP_CONNECTION, timeout=10)
    # Nudge the client back up rather than waiting on NM's own retry timer.
    _run_root("nmcli", "device", "connect", WIFI_INTERFACE, timeout=60)
    if code != 0:
        text = (err or out).strip()
        log.warning("hotspot stop: %s", text)
    log.info("hotspot down")
    return True, "Hotspot off"


def wifi_connected() -> bool:
    """True when wlan0 has an active connection that is not our own AP."""
    code, out, _ = _run_result(
        "nmcli", "-t", "-f", "DEVICE,STATE,CONNECTION", "device", "status",
        timeout=10)
    if code != 0:
        return False
    for line in out.splitlines():
        fields = _split_terse(line)
        if len(fields) >= 3 and fields[0] == WIFI_INTERFACE:
            return fields[1] == "connected" and fields[2] != AP_CONNECTION
    return False


def set_pairing(enabled: bool) -> None:
    """Pairing mode = adapter discoverable + pairable, so a host that forgot
    the pedal can find it again and re-pair."""
    word = "on" if enabled else "off"
    for command in ("discoverable", "pairable"):
        _run("bluetoothctl", command, word)
    log.info("pairing mode set %s", word)
