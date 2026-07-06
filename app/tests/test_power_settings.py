"""Unit tests for PowerLogic and SettingsLogic."""

import copy
import unittest

from config.defaults import default_config
from logic.power import PowerLogic
from logic.settings import MAIN_ITEMS, SettingsLogic
from state.manager import StateManager


class PowerLogicTest(unittest.TestCase):
    def setUp(self):
        config = default_config()
        self.state = StateManager(config)
        self.logic = PowerLogic(config, self.state)

    def tap(self, t):
        self.logic.handle_event((0, "press", t))
        self.logic.handle_event((0, "release", t + 0.05))

    def test_single_press_does_nothing(self):
        self.tap(0.0)
        self.assertFalse(self.state.settings_open)

    def test_double_press_opens_settings(self):
        self.tap(0.0)
        self.tap(0.3)
        self.assertTrue(self.state.settings_open)

    def test_slow_presses_do_not_open(self):
        self.tap(0.0)
        self.tap(1.0)
        self.assertFalse(self.state.settings_open)
        # But the second press starts a new window.
        self.tap(1.3)
        self.assertTrue(self.state.settings_open)

    def test_double_press_again_closes(self):
        self.tap(0.0)
        self.tap(0.3)
        self.tap(2.0)
        self.tap(2.3)
        self.assertFalse(self.state.settings_open)

    def test_triple_press_does_not_retoggle(self):
        self.tap(0.0)
        self.tap(0.2)
        self.tap(0.4)  # third press starts a fresh window, no toggle
        self.assertTrue(self.state.settings_open)

    def test_hold_fires_shutdown_stub_once(self):
        self.logic.handle_event((0, "press", 0.0))
        self.logic.tick(1.0)
        self.assertFalse(self.logic._hold_fired)
        self.logic.tick(3.0)
        self.assertTrue(self.logic._hold_fired)


class FakeSysinfo:
    def __init__(self):
        self.pairing_calls = []
        self.ssid = "HomeNet"
        self.discoverable = False

    def wifi_ssid(self):
        return self.ssid

    def ip_address(self):
        return "192.168.1.50"

    def hostname(self):
        return "guitar-pedal"

    def bluetooth_status(self):
        return {"powered": True, "discoverable": self.discoverable}

    def usb_gadget_state(self):
        return "configured"

    def set_pairing(self, enabled):
        self.pairing_calls.append(enabled)


class FakePresets:
    """In-memory stand-in for config.presets."""

    def __init__(self):
        self.configs = {}
        for name in ("Jazz", "Rock"):
            config = default_config()
            config["preset_name"] = name
            self.configs[name] = config

    def list_presets(self):
        return [{"name": n, "modified": 0} for n in sorted(self.configs)]

    def load_preset(self, name):
        if name not in self.configs:
            raise ValueError(f"no preset named {name!r}")
        return copy.deepcopy(self.configs[name])


class FakeMidi:
    usb_open = True
    ble_state = "advertising"


class SettingsLogicTest(unittest.TestCase):
    def setUp(self):
        config = default_config()
        self.state = StateManager(config)
        self.state.settings_open = True
        self.sysinfo = FakeSysinfo()
        self.presets = FakePresets()
        self.saved = []
        self.logic = SettingsLogic(
            self.state, midi=FakeMidi(), sysinfo_module=self.sysinfo,
            presets_module=self.presets, save=self.saved.append,
        )
        # Run worker threads inline so tests are deterministic.
        self.logic._spawn = lambda fn, *args, **kwargs: fn(*args)
        self.logic.tick(0.0)  # opens the menu: builds rows + first refresh

    def press(self, num):
        self.logic.handle_event((num, "press", 0.0))

    def rows(self):
        return dict(self.state.settings_rows)

    def test_open_builds_rows_with_status(self):
        rows = self.rows()
        self.assertEqual(rows["Wi-Fi"], "HomeNet")
        self.assertEqual(rows["Bluetooth MIDI"], "advertising")
        self.assertEqual(rows["USB MIDI"], "host connected")
        self.assertIn("192.168.1.50", rows["IP / hostname"])
        self.assertIn("guitar-pedal", rows["IP / hostname"])
        self.assertEqual(rows["Pairing mode"], "OFF")

    def test_down_up_navigation_wraps(self):
        self.press(7)
        self.assertEqual(self.state.settings_index, 1)
        self.press(6)
        self.press(6)
        self.assertEqual(self.state.settings_index, len(MAIN_ITEMS) - 1)

    def test_exit_button_closes(self):
        self.press(10)
        self.assertFalse(self.state.settings_open)
        self.assertEqual(self.state.settings_index, 0)

    def test_select_exit_item_closes(self):
        self.state.settings_index = MAIN_ITEMS.index("exit")
        self.press(9)
        self.assertFalse(self.state.settings_open)

    def test_select_info_row_stays_open(self):
        self.press(9)
        self.assertTrue(self.state.settings_open)

    def test_release_events_ignored(self):
        self.logic.handle_event((7, "release", 0.0))
        self.assertEqual(self.state.settings_index, 0)

    def test_pairing_toggle(self):
        self.state.settings_index = MAIN_ITEMS.index("pairing")
        self.press(9)
        self.assertEqual(self.sysinfo.pairing_calls, [True])
        self.assertEqual(self.rows()["Pairing mode"], "ON")
        self.press(9)
        self.assertEqual(self.sysinfo.pairing_calls, [True, False])
        self.assertEqual(self.rows()["Pairing mode"], "OFF")

    def _open_presets(self):
        self.state.settings_index = MAIN_ITEMS.index("preset")
        self.press(9)

    def test_preset_view_lists_presets_and_back(self):
        self._open_presets()
        self.assertEqual(self.state.settings_view, "presets")
        self.assertEqual([r[0] for r in self.state.settings_rows],
                         ["Jazz", "Rock", "Back"])

    def test_preset_load_installs_and_saves(self):
        self._open_presets()
        self.press(7)  # move from Jazz to Rock
        self.press(9)
        self.assertEqual(self.state.config["preset_name"], "Rock")
        self.assertEqual(len(self.saved), 1)
        self.assertEqual(self.state.settings_view, "main")
        self.assertTrue(self.state.settings_open)

    def test_preset_current_marker_and_initial_selection(self):
        self.state.config["preset_name"] = "Rock"
        self._open_presets()
        self.assertEqual(self.state.settings_index, 1)  # Rock preselected
        self.assertEqual(self.rows()["Rock"], "current")

    def test_preset_back_returns_to_main(self):
        self._open_presets()
        self.state.settings_index = 2  # "Back"
        self.press(9)
        self.assertEqual(self.state.settings_view, "main")
        self.assertEqual(self.state.settings_index, MAIN_ITEMS.index("preset"))

    def test_exit_button_in_presets_goes_back_not_closed(self):
        self._open_presets()
        self.press(10)
        self.assertTrue(self.state.settings_open)
        self.assertEqual(self.state.settings_view, "main")

    def test_reopen_resets_to_main_view(self):
        self._open_presets()
        self.press(10)  # back to main
        self.press(10)  # close
        self.state.settings_open = True
        self.logic.tick(10.0)
        self.assertEqual(self.state.settings_view, "main")
        self.assertEqual(self.state.settings_index, 0)


if __name__ == "__main__":
    unittest.main()
