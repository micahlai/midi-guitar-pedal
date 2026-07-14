"""Header status strings (logic/status.py).

MIDI reports whether a HOST is actually connected, not whether the transport
happens to be up: an open USB port with no cable, or BLE sitting there
advertising, is not a connection.
"""

import unittest

from config.defaults import default_config
from logic.status import StatusLogic
from state.manager import StateManager


class FakeMidi:
    def __init__(self, usb_open=True, ble_state="off"):
        self.usb_open = usb_open
        self.ble_state = ble_state


class FakeSysinfo:
    def __init__(self, ssid="Hogwarts", ap=False, usb="not attached"):
        self.ssid = ssid
        self.ap = ap
        self.usb = usb

    def wifi_ssid(self):
        return self.ssid

    def ap_active(self):
        return self.ap

    def usb_gadget_state(self):
        return self.usb


class MidiStatusTest(unittest.TestCase):
    def text(self, usb_attached, ble_state, usb_open=True):
        state = StateManager(default_config())
        logic = StatusLogic(
            state, midi=FakeMidi(usb_open=usb_open, ble_state=ble_state),
            sysinfo_module=FakeSysinfo(
                usb="configured" if usb_attached else "not attached"))
        logic._refresh_network()  # populates the cached USB attach state
        return logic._midi_text()

    def test_no_connection(self):
        self.assertEqual(self.text(False, "off"), "no midi connection")

    def test_usb_only(self):
        self.assertEqual(self.text(True, "off"), "usb midi")

    def test_ble_only(self):
        self.assertEqual(self.text(False, "connected"), "ble midi")

    def test_both(self):
        self.assertEqual(self.text(True, "connected"), "usb/ble midi")

    def test_advertising_ble_is_not_a_connection(self):
        """Advertising means nobody has connected yet."""
        self.assertEqual(self.text(False, "advertising"), "no midi connection")

    def test_open_usb_port_without_a_host_is_not_a_connection(self):
        """usb_open only means the pedal opened its own port; the gadget is
        "configured" only once a host has actually enumerated it."""
        self.assertEqual(self.text(False, "off", usb_open=True),
                         "no midi connection")


class NetworkStatusTest(unittest.TestCase):
    def refresh(self, **kwargs):
        state = StateManager(default_config())
        logic = StatusLogic(state, midi=FakeMidi(),
                            sysinfo_module=FakeSysinfo(**kwargs))
        logic._refresh_network()
        return state.header_network

    def test_shows_the_joined_ssid(self):
        self.assertEqual(self.refresh(ssid="Hogwarts"), "Hogwarts")

    def test_shows_the_hotspot_when_hosting(self):
        self.assertEqual(self.refresh(ap=True), "AP GuitarPedal")

    def test_reports_no_wifi(self):
        self.assertEqual(self.refresh(ssid=None), "no Wi-Fi")


if __name__ == "__main__":
    unittest.main()
