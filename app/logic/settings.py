"""On-device settings menu (Milestone 15) — wireless status, pairing mode,
IP/hostname and preset switching, usable with only the footswitches.

    B6 = up, B7 = down, B9 = select, B10 = exit/back

Navigation and row building are pure logic. System status (Wi-Fi, Bluetooth,
USB, IP) comes from hardware/sysinfo.py, gathered on a short-lived worker
thread every REFRESH_SECONDS while the menu is open so shell-outs never stall
the 10 ms main loop. The renderer just draws state.settings_rows.

Wi-Fi setup: selecting the Wi-Fi row opens a popup listing discovered
networks (view "wifi"; scan/connect run on worker threads). Choosing a
secured network opens a password popup (view "wifi_password") typed on a
USB keyboard plugged into the Pi — key events arrive via handle_key() from
the main loop (Enter = connect, Esc = back, Backspace edits; B9/B10 mirror
Enter/Esc for keyboard-less navigation).
"""

import logging
import threading

from config import presets
from config.defaults import copy_device_settings
from config.loader import save_config
from hardware import sysinfo

log = logging.getLogger("controller.logic.settings")

BUTTON_UP = 6
BUTTON_DOWN = 7
BUTTON_SELECT = 9
BUTTON_EXIT = 10

# pygame key constants (numeric so this module stays hardware-free).
KEY_BACKSPACE = 8
KEY_RETURN = 13
KEY_ESCAPE = 27
KEY_KP_ENTER = 1073741912

PASSWORD_MAX_CHARS = 63  # WPA passphrase limit

REFRESH_SECONDS = 2.0

# Main-view items, in display order. Info rows refresh on select; pairing
# toggles; preset opens the preset list view; exit closes the menu.
MAIN_ITEMS = ("wifi", "bluetooth", "usb", "network", "pairing", "preset", "exit")


class SettingsLogic:
    def __init__(self, state, midi=None, sysinfo_module=sysinfo,
                 presets_module=presets, save=save_config):
        self.state = state
        self.midi = midi  # MidiEngine, for live USB/BLE transport status
        self.sysinfo = sysinfo_module
        self.presets = presets_module
        self.save = save
        self._info: dict = {}
        self._refreshing = False
        self._last_refresh: float | None = None
        self._was_open = False
        # Wi-Fi popup: what each popup row does when selected (parallel to
        # state.settings_popup_rows), plus in-flight worker flags.
        self._wifi_items: list[tuple] = []
        self._scanning = False
        self._connecting = False

    # --- events (main loop) --------------------------------------------------

    def handle_event(self, event: tuple) -> None:
        num, kind, _t = event
        if kind != "press":
            return
        if self.state.settings_view == "wifi_password":
            if num == BUTTON_SELECT:
                self._submit_password()
            elif num == BUTTON_EXIT:
                self._show_wifi(rescan=False)
            return
        rows = len(self._nav_rows()) or 1
        if num == BUTTON_UP:
            self.state.settings_index = (self.state.settings_index - 1) % rows
        elif num == BUTTON_DOWN:
            self.state.settings_index = (self.state.settings_index + 1) % rows
        elif num == BUTTON_SELECT:
            self._select()
        elif num == BUTTON_EXIT:
            if self.state.settings_view in ("presets", "wifi"):
                self._show_main()
            else:
                self._close()

    def handle_key(self, payload: tuple) -> None:
        """USB keyboard input (key, unicode char) — password entry only."""
        key, char = payload
        if self.state.settings_view != "wifi_password" or self._connecting:
            return
        if key in (KEY_RETURN, KEY_KP_ENTER):
            self._submit_password()
        elif key == KEY_BACKSPACE:
            self.state.settings_password = self.state.settings_password[:-1]
        elif key == KEY_ESCAPE:
            self._show_wifi(rescan=False)
        elif (char and len(char) == 1 and char.isprintable()
                and len(self.state.settings_password) < PASSWORD_MAX_CHARS):
            self.state.settings_password += char

    def _nav_rows(self) -> list:
        return (self.state.settings_popup_rows
                if self.state.settings_view == "wifi"
                else self.state.settings_rows)

    def tick(self, now: float) -> None:
        """Open/close bookkeeping plus the periodic status refresh."""
        if not self.state.settings_open:
            self._was_open = False
            self._last_refresh = None
            return
        if not self._was_open:
            self._was_open = True
            self.state.settings_view = "main"
            self.state.settings_index = 0
            self.state.settings_password = ""
            self.state.settings_wifi_status = ""
            self._build_rows()
        if self._refreshing:
            return
        if self._last_refresh is None or now - self._last_refresh >= REFRESH_SECONDS:
            self._last_refresh = now
            self._refreshing = True
            self._spawn(self._refresh, name="settings-refresh")

    @staticmethod
    def _spawn(fn, *args, name="settings-worker"):
        threading.Thread(target=fn, args=args, daemon=True, name=name).start()

    # --- selection -------------------------------------------------------------

    def _select(self) -> None:
        if self.state.settings_view == "presets":
            index = self.state.settings_index
            if index >= len(self.state.settings_presets):  # the "Back" row
                self._show_main()
            else:
                self._load_preset(self.state.settings_presets[index])
            return
        if self.state.settings_view == "wifi":
            self._select_wifi()
            return
        item = MAIN_ITEMS[min(self.state.settings_index, len(MAIN_ITEMS) - 1)]
        if item == "exit":
            self._close()
        elif item == "pairing":
            self._toggle_pairing()
        elif item == "preset":
            self._show_presets()
        elif item == "wifi":
            self._show_wifi()
        else:
            self._last_refresh = None  # info rows: select = refresh now

    def _toggle_pairing(self) -> None:
        enabled = not self._info.get("pairing", False)
        self._info["pairing"] = enabled  # optimistic; the next refresh confirms
        self._build_rows()
        self._spawn(self.sysinfo.set_pairing, enabled, name="settings-pairing")

    def _show_presets(self) -> None:
        self.state.settings_presets = [p["name"] for p in self.presets.list_presets()]
        self.state.settings_view = "presets"
        current = self.state.config.get("preset_name", "")
        names = self.state.settings_presets
        self.state.settings_index = names.index(current) if current in names else 0
        self._build_rows()

    def _show_main(self, select: str | None = None) -> None:
        previous = self.state.settings_view
        if select is None:
            select = "wifi" if previous in ("wifi", "wifi_password") else "preset"
        self.state.settings_view = "main"
        self.state.settings_index = MAIN_ITEMS.index(select)
        self._build_rows()

    # --- Wi-Fi setup popup ---------------------------------------------------

    def _show_wifi(self, rescan: bool = True) -> None:
        self.state.settings_view = "wifi"
        self.state.settings_index = 0
        self.state.settings_password = ""
        if rescan or not self.state.settings_networks:
            self.state.settings_networks = []
            self.state.settings_wifi_status = "Scanning…"
            self._scanning = True
            self._build_wifi_rows()
            self._spawn(self._scan_wifi, name="settings-wifi-scan")
        else:  # back from password entry: keep the last scan
            self.state.settings_wifi_status = ""
            self._build_wifi_rows()

    def _scan_wifi(self) -> None:
        """Worker thread: discover networks, then rebuild the popup rows."""
        try:
            networks = self.sysinfo.wifi_scan()
        except Exception:
            log.exception("wifi scan failed")
            networks = None
        self._scanning = False
        if not (self.state.settings_open and self.state.settings_view == "wifi"):
            return
        self.state.settings_networks = networks or []
        if networks is None:
            self.state.settings_wifi_status = "Scan failed"
        else:
            self.state.settings_wifi_status = "" if networks else "No networks found"
        self.state.settings_index = 0
        self._build_wifi_rows()

    def _select_wifi(self) -> None:
        if self._scanning or self._connecting:
            return
        index = min(self.state.settings_index, len(self._wifi_items) - 1)
        item = self._wifi_items[index] if self._wifi_items else ("back",)
        if item[0] == "back":
            self._show_main()
        elif item[0] == "rescan":
            self._show_wifi()
        elif item[0] == "network":
            network = item[1]
            if network["in_use"]:
                self.state.settings_wifi_status = f"Already connected to {network['ssid']}"
                self._build_wifi_rows()
            elif network["secured"]:
                self._show_password(network["ssid"])
            else:
                self._start_connect(network["ssid"], None)

    def _show_password(self, ssid: str) -> None:
        self.state.settings_view = "wifi_password"
        self.state.settings_wifi_ssid = ssid
        self.state.settings_password = ""
        self.state.settings_wifi_status = ""

    def _submit_password(self) -> None:
        if self._connecting:
            return
        if not self.state.settings_password:
            self.state.settings_wifi_status = "Password required"
            return
        self._start_connect(self.state.settings_wifi_ssid,
                            self.state.settings_password)

    def _start_connect(self, ssid: str, password: str | None) -> None:
        self._connecting = True
        self.state.settings_wifi_status = f"Connecting to {ssid}…"
        if self.state.settings_view == "wifi":
            self._build_wifi_rows()
        self._spawn(self._connect_wifi, ssid, password,
                    name="settings-wifi-connect")

    def _connect_wifi(self, ssid: str, password: str | None) -> None:
        """Worker thread: join the network (blocks up to ~60 s)."""
        try:
            ok, message = self.sysinfo.wifi_connect(ssid, password)
        except Exception:
            log.exception("wifi connect failed")
            ok, message = False, "Connection failed"
        self._connecting = False
        if not self.state.settings_open:
            return
        self.state.settings_wifi_status = message
        if ok:
            # Back to the main view; the forced refresh shows the new
            # SSID/IP on the Wi-Fi and network rows.
            self._show_main(select="wifi")
            self._last_refresh = None
        elif self.state.settings_view == "wifi":
            self._build_wifi_rows()  # failure message under the list

    def _build_wifi_rows(self) -> None:
        """Compose the popup's (label, value) rows plus the parallel action
        list; assigned whole so the render thread never sees them half-built."""
        items: list[tuple] = []
        rows: list[tuple[str, str]] = []
        if not self._scanning:
            for network in self.state.settings_networks:
                if network["in_use"]:
                    value = "connected"
                else:
                    value = (f"{network['signal']}%  ·  "
                             + ("secured" if network["secured"] else "open"))
                items.append(("network", network))
                rows.append((network["ssid"], value))
            items.append(("rescan",))
            rows.append(("Rescan", ""))
        items.append(("back",))
        rows.append(("Back", ""))
        self._wifi_items = items
        self.state.settings_popup_rows = rows

    def _load_preset(self, name: str) -> None:
        try:
            config = self.presets.load_preset(name)
        except (ValueError, OSError) as e:
            log.error("preset load failed: %s", e)
            return
        # Presets never carry device-scoped settings; keep this device's.
        copy_device_settings(self.state.config, config)
        self.state.install_config(config)
        self.save(self.state.config)
        log.info("preset loaded from settings menu: %s", name)
        self._show_main()

    def _close(self) -> None:
        self.state.settings_open = False
        self.state.settings_view = "main"
        self.state.settings_index = 0
        self.state.settings_password = ""
        self.state.settings_wifi_status = ""
        log.info("settings closed")

    # --- status rows -------------------------------------------------------------

    def _refresh(self) -> None:
        """Worker thread: gather system status, then rebuild the rows."""
        try:
            info = {
                "ssid": self.sysinfo.wifi_ssid(),
                "ip": self.sysinfo.ip_address(),
                "hostname": self.sysinfo.hostname(),
                "usb": self.sysinfo.usb_gadget_state(),
            }
            bluetooth = self.sysinfo.bluetooth_status()
            info["bt_powered"] = bluetooth["powered"]
            info["pairing"] = bluetooth["discoverable"]
            self._info.update(info)
            if self.state.settings_open and self.state.settings_view == "main":
                self._build_rows()
        except Exception:
            log.exception("settings refresh failed")
        finally:
            self._refreshing = False

    def _build_rows(self) -> None:
        """Compose (label, value) display rows into state.settings_rows.
        Assigned as a whole list so the render thread never sees a half-built
        view."""
        if self.state.settings_view == "presets":
            current = self.state.config.get("preset_name", "")
            rows = [(name, "current" if name == current else "")
                    for name in self.state.settings_presets]
            rows.append(("Back", ""))
            self.state.settings_rows = rows
            return

        info = self._info
        ssid = info.get("ssid")
        wifi = ssid or ("not connected" if "ssid" in info else "…")

        ble = self.midi.ble_state if self.midi is not None else "off"
        if not info.get("bt_powered", True):
            ble = "adapter off"

        usb = {"configured": "host connected", "not attached": "no host"}.get(
            info.get("usb", ""), info.get("usb", "…"))
        if self.midi is not None and not self.midi.usb_open:
            usb = "port not open"

        network = f"{info.get('ip') or '—'}  ·  {info.get('hostname') or '…'}"
        self.state.settings_rows = [
            ("Wi-Fi", wifi),
            ("Bluetooth MIDI", ble),
            ("USB MIDI", usb),
            ("IP / hostname", network),
            ("Pairing mode", "ON" if info.get("pairing") else "OFF"),
            ("Preset", self.state.config.get("preset_name") or "—"),
            ("Exit", ""),
        ]
