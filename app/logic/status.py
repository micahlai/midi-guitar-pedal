"""Header status strings for the network/MIDI items in the top bar.

The renderer runs at 30 fps and must never shell out, so the values it draws
are refreshed here on a worker thread and left in StateManager for it to read.
MIDI transport state is already in memory (MidiEngine properties); only the
network side costs an nmcli call, hence the interval.
"""

import logging
import threading

from hardware import sysinfo

log = logging.getLogger("controller.logic.status")

# Short enough that plugging a USB host in shows up promptly in the header.
REFRESH_SECONDS = 2.0


class StatusLogic:
    def __init__(self, state, midi=None, sysinfo_module=sysinfo):
        self.state = state
        self.midi = midi
        self.sysinfo = sysinfo_module
        self._last = None
        self._busy = False
        self._usb_attached = False

    def tick(self, now: float) -> None:
        # MIDI is a cheap in-memory read; do it every tick so the header
        # reacts to a host connecting the moment it happens.
        self.state.header_midi = self._midi_text()
        if self._busy:
            return
        if self._last is None or now - self._last >= REFRESH_SECONDS:
            self._last = now
            self._busy = True
            threading.Thread(target=self._refresh_network, daemon=True,
                             name="status-network").start()

    def _midi_text(self) -> str:
        """Whether a HOST is actually connected on each transport — not merely
        whether the transport is up. An open USB port with nothing plugged in,
        or BLE sitting there advertising, is not a connection.

        USB: the gadget reports "configured" once a host has enumerated it
        (usb_open only means the pedal opened its own port). BLE: a central has
        actually connected.
        """
        usb = self._usb_attached and self.midi is not None and self.midi.usb_open
        ble = self.midi is not None and self.midi.ble_state == "connected"
        if usb and ble:
            return "USB/BLE MIDI"
        if usb:
            return "USB MIDI"
        if ble:
            return "BLE MIDI"
        return "No MIDI Connection"

    def _refresh_network(self) -> None:
        try:
            if self.sysinfo.ap_active():
                ssid = self.state.config.get("hotspot", {}).get("ssid", "")
                self.state.header_network = f"AP {ssid}".strip()
            else:
                ssid = self.sysinfo.wifi_ssid()
                self.state.header_network = ssid or "no Wi-Fi"
            # Cached, not read per tick: the renderer asks for the MIDI text
            # every frame and this is a sysfs read.
            self._usb_attached = self.sysinfo.usb_gadget_state() == "configured"
        except Exception:
            log.exception("status refresh failed")
        finally:
            self._busy = False
