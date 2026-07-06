"""On-device settings menu (Milestone 15) — wireless status, pairing mode,
IP/hostname and preset switching, usable with only the footswitches.

    B6 = up, B7 = down, B9 = select, B10 = exit/back

Navigation and row building are pure logic. System status (Wi-Fi, Bluetooth,
USB, IP) comes from hardware/sysinfo.py, gathered on a short-lived worker
thread every REFRESH_SECONDS while the menu is open so shell-outs never stall
the 10 ms main loop. The renderer just draws state.settings_rows.
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

    # --- events (main loop) --------------------------------------------------

    def handle_event(self, event: tuple) -> None:
        num, kind, _t = event
        if kind != "press":
            return
        rows = len(self.state.settings_rows) or 1
        if num == BUTTON_UP:
            self.state.settings_index = (self.state.settings_index - 1) % rows
        elif num == BUTTON_DOWN:
            self.state.settings_index = (self.state.settings_index + 1) % rows
        elif num == BUTTON_SELECT:
            self._select()
        elif num == BUTTON_EXIT:
            if self.state.settings_view == "presets":
                self._show_main()
            else:
                self._close()

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
        item = MAIN_ITEMS[min(self.state.settings_index, len(MAIN_ITEMS) - 1)]
        if item == "exit":
            self._close()
        elif item == "pairing":
            self._toggle_pairing()
        elif item == "preset":
            self._show_presets()
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

    def _show_main(self) -> None:
        self.state.settings_view = "main"
        self.state.settings_index = MAIN_ITEMS.index("preset")
        self._build_rows()

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
