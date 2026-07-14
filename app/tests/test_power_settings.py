"""Unit tests for PowerLogic and SettingsLogic."""

import copy
import unittest

from config.defaults import default_config
from hardware.constants import BUTTON_NUM_POWER
from logic.keypad import KEY_DELETE, KEY_SHIFT
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
        self.networks = [
            {"ssid": "HomeNet", "signal": 82, "secured": True, "in_use": True},
            {"ssid": "CoffeeShop", "signal": 61, "secured": False, "in_use": False},
            {"ssid": "Studio5G", "signal": 47, "secured": True, "in_use": False},
        ]
        self.connect_calls = []
        self.connect_result = (True, "Connected to Studio5G")
        self.scan_forced = []
        self.ap = False
        self.ap_calls = []
        self.ap_start_result = (True, "Hosting GuitarPedal")

    def wifi_scan(self, force=False):
        self.scan_forced.append(force)
        return copy.deepcopy(self.networks)

    def wifi_connect(self, ssid, password=None):
        self.connect_calls.append((ssid, password))
        return self.connect_result

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

    def ap_active(self):
        return self.ap

    def ap_start(self, ssid, password):
        self.ap_calls.append(("start", ssid, password))
        ok, message = self.ap_start_result
        if ok:
            self.ap = True
            self.ssid = None  # radio left the client network
        return ok, message

    def ap_stop(self):
        self.ap_calls.append(("stop",))
        self.ap = False
        return True, "Hotspot off"

    def wifi_connected(self):
        return self.ssid is not None and not self.ap


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
        self.state.settings_index = MAIN_ITEMS.index("network")
        self.press(9)
        self.assertTrue(self.state.settings_open)
        self.assertEqual(self.state.settings_view, "main")

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

    def test_hotspot_toggle_starts_and_stops_the_ap(self):
        self.state.settings_index = MAIN_ITEMS.index("hotspot")
        self.press(9)
        self.assertEqual(self.sysinfo.ap_calls,
                         [("start", "GuitarPedal", "pedalsetup")])
        self.assertTrue(self.sysinfo.ap)
        self.press(9)
        self.assertEqual(self.sysinfo.ap_calls[-1], ("stop",))
        self.assertFalse(self.sysinfo.ap)

    def test_hotspot_row_shows_ssid_while_hosting(self):
        self.state.settings_index = MAIN_ITEMS.index("hotspot")
        self.press(9)
        self.assertEqual(self.rows()["Hotspot"], "ON  ·  GuitarPedal")
        # The radio can't also be a client, so Wi-Fi must not claim an SSID.
        self.assertEqual(self.rows()["Wi-Fi"], "hosting")

    def test_failed_hotspot_start_rolls_the_row_back(self):
        self.sysinfo.ap_start_result = (False, "Hotspot failed")
        self.state.settings_index = MAIN_ITEMS.index("hotspot")
        self.press(9)
        self.assertEqual(self.rows()["Hotspot"], "OFF")
        self.assertEqual(self.state.settings_wifi_status, "Hotspot failed")

    def _open_header(self):
        self.state.settings_index = MAIN_ITEMS.index("header")
        self.press(9)

    def test_header_popup_lists_items_with_positions(self):
        self._open_header()
        self.assertEqual(self.state.settings_view, "header")
        rows = dict(self.state.settings_popup_rows)
        self.assertEqual(rows["Patch"], "far left")
        self.assertEqual(rows["BPM"], "far right")
        self.assertEqual(rows["MIDI status"], "—")

    def test_header_b1_to_b5_place_the_selected_item(self):
        self._open_header()
        self.press(7)  # down: BPM
        self.press(3)  # B3 = middle
        self.assertEqual(self.state.config["ui"]["header"],
                         ["patch", None, "bpm", None, None])
        self.assertEqual(self.saved[-1]["ui"]["header"][2], "bpm")

    def test_header_placing_onto_an_occupied_slot_evicts(self):
        self._open_header()
        self.press(7)          # BPM
        self.press(1)          # B1 = far left, where Patch lives
        self.assertEqual(self.state.config["ui"]["header"],
                         ["bpm", None, None, None, None])

    def test_header_pressing_its_own_slot_removes_it(self):
        self._open_header()
        self.press(1)  # Patch is already at far left -> toggles off
        self.assertEqual(self.state.config["ui"]["header"],
                         [None, None, None, None, "bpm"])

    def test_header_b10_returns_to_menu(self):
        self._open_header()
        self.press(10)
        self.assertEqual(self.state.settings_view, "main")

    def test_header_row_counts_filled_positions(self):
        self.assertEqual(self.rows()["Header"], "2 set")
        self.state.config["ui"]["header"] = [None] * 5
        self.logic._build_rows()
        self.assertEqual(self.rows()["Header"], "0 set")

    def _open_hotspot_key(self):
        self.state.settings_index = MAIN_ITEMS.index("hotspot_key")
        self.press(9)

    def test_hotspot_password_editor_prefills_current_key(self):
        """Prefilled, not blank — editing one character of a 12-char key by
        retyping the whole thing on footswitches would be miserable."""
        self._open_hotspot_key()
        self.assertEqual(self.state.settings_view, "hotspot_password")
        self.assertEqual(self.state.settings_password, "pedalsetup")
        self.assertEqual(self.state.settings_password_cursor, len("pedalsetup"))

    def test_hotspot_password_saves_on_power(self):
        self._open_hotspot_key()
        for _ in range(len("pedalsetup")):
            self.press(KEY_DELETE)
        self.type_text("newsecret1")
        self.press(BUTTON_NUM_POWER)
        self.assertEqual(self.state.config["hotspot"]["password"], "newsecret1")
        self.assertEqual(self.saved[-1]["hotspot"]["password"], "newsecret1")
        self.assertEqual(self.state.settings_view, "main")

    def test_hotspot_password_rejects_short_key(self):
        """WPA2 refuses < 8 chars; catching it here beats a cryptic nmcli
        failure later, when the radio has already left the network."""
        self._open_hotspot_key()
        for _ in range(len("pedalsetup")):
            self.press(KEY_DELETE)
        self.type_text("short")
        self.press(BUTTON_NUM_POWER)
        self.assertEqual(self.state.config["hotspot"]["password"], "pedalsetup")
        self.assertEqual(self.state.settings_view, "hotspot_password")
        self.assertIn("8+", self.state.settings_wifi_status)

    def test_hotspot_password_row_shows_the_key(self):
        self.assertEqual(self.rows()["Hotspot password"], "pedalsetup")

    def test_delete_on_empty_hotspot_key_returns_to_menu(self):
        self._open_hotspot_key()
        for _ in range(len("pedalsetup")):
            self.press(KEY_DELETE)
        self.press(KEY_DELETE)  # now empty: backs out
        self.assertEqual(self.state.settings_view, "main")
        self.assertEqual(self.state.config["hotspot"]["password"], "pedalsetup")

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

    def test_preset_load_keeps_device_settings(self):
        self.state.config["device"]["name"] = "This Pedal"
        self.state.config["midi"]["ble_enabled"] = False
        # The preset file claims different device settings; they must lose.
        self.presets.configs["Rock"]["device"]["name"] = "Other Pedal"
        self._open_presets()
        self.press(7)
        self.press(9)
        self.assertEqual(self.state.config["preset_name"], "Rock")
        self.assertEqual(self.state.config["device"]["name"], "This Pedal")
        self.assertFalse(self.state.config["midi"]["ble_enabled"])

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

    # --- Wi-Fi setup popup ---------------------------------------------------

    def _open_wifi(self):
        self.state.settings_index = MAIN_ITEMS.index("wifi")
        self.press(9)

    def type_text(self, text):
        for ch in text:
            self.logic.handle_key((ord(ch.lower()), ch))

    def test_opening_and_rescan_both_request_a_real_sweep(self):
        """NM's cached list decays to just the associated AP while connected,
        so the popup must force a sweep rather than trust the cache."""
        self._open_wifi()
        self.assertEqual(self.sysinfo.scan_forced, [True])
        self.state.settings_index = len(self.sysinfo.networks)  # the Rescan row
        self.press(9)
        self.assertEqual(self.sysinfo.scan_forced, [True, True])

    def test_wifi_row_opens_network_popup(self):
        self._open_wifi()
        self.assertEqual(self.state.settings_view, "wifi")
        self.assertEqual([r[0] for r in self.state.settings_popup_rows],
                         ["HomeNet", "CoffeeShop", "Studio5G", "Rescan", "Back"])
        rows = dict(self.state.settings_popup_rows)
        self.assertEqual(rows["HomeNet"], "connected")
        self.assertEqual(rows["CoffeeShop"], "61%  ·  open")
        self.assertEqual(rows["Studio5G"], "47%  ·  secured")
        self.assertEqual(self.state.settings_wifi_status, "")
        # Main rows behind the popup are untouched.
        self.assertEqual(self.rows()["Wi-Fi"], "HomeNet")

    def test_wifi_scan_failure_shows_status(self):
        self.sysinfo.wifi_scan = lambda: None
        self._open_wifi()
        self.assertEqual(self.state.settings_wifi_status, "Scan failed")
        self.assertEqual([r[0] for r in self.state.settings_popup_rows],
                         ["Rescan", "Back"])

    def test_wifi_back_returns_to_main(self):
        self._open_wifi()
        self.state.settings_index = 4  # "Back"
        self.press(9)
        self.assertEqual(self.state.settings_view, "main")
        self.assertEqual(self.state.settings_index, MAIN_ITEMS.index("wifi"))

    def test_wifi_exit_button_goes_back_not_closed(self):
        self._open_wifi()
        self.press(10)
        self.assertTrue(self.state.settings_open)
        self.assertEqual(self.state.settings_view, "main")

    def test_open_network_connects_without_password(self):
        self._open_wifi()
        self.state.settings_index = 1  # CoffeeShop (open)
        self.press(9)
        self.assertEqual(self.sysinfo.connect_calls, [("CoffeeShop", None)])
        # Success returns to the main view and forces a status refresh.
        self.assertEqual(self.state.settings_view, "main")
        self.assertIsNone(self.logic._last_refresh)

    def test_in_use_network_does_not_reconnect(self):
        self._open_wifi()
        self.press(9)  # HomeNet, already connected
        self.assertEqual(self.sysinfo.connect_calls, [])
        self.assertEqual(self.state.settings_view, "wifi")
        self.assertIn("Already connected", self.state.settings_wifi_status)

    def test_secured_network_opens_password_entry(self):
        self._open_wifi()
        self.state.settings_index = 2  # Studio5G (secured)
        self.press(9)
        self.assertEqual(self.state.settings_view, "wifi_password")
        self.assertEqual(self.state.settings_wifi_ssid, "Studio5G")
        self.assertEqual(self.state.settings_password, "")

    def _open_password(self):
        self._open_wifi()
        self.state.settings_index = 2
        self.press(9)

    def test_typing_backspace_and_enter_connects(self):
        self._open_password()
        self.type_text("hunter42x")
        self.logic.handle_key((8, "\x08"))  # backspace
        self.assertEqual(self.state.settings_password, "hunter42")
        self.logic.handle_key((13, "\r"))  # enter
        self.assertEqual(self.sysinfo.connect_calls, [("Studio5G", "hunter42")])
        self.assertEqual(self.state.settings_view, "main")

    def test_power_button_submits_password(self):
        """Every footswitch types a character now, so POWER is confirm."""
        self._open_password()
        self.type_text("hunter42")
        self.press(BUTTON_NUM_POWER)
        self.assertEqual(self.sysinfo.connect_calls, [("Studio5G", "hunter42")])

    def test_empty_password_not_submitted(self):
        self._open_password()
        self.logic.handle_key((13, "\r"))
        self.assertEqual(self.sysinfo.connect_calls, [])
        self.assertEqual(self.state.settings_view, "wifi_password")
        self.assertEqual(self.state.settings_wifi_status, "Password required")

    def test_failed_connect_stays_in_password_view(self):
        self.sysinfo.connect_result = (False, "Wrong password")
        self._open_password()
        self.type_text("oops1234")
        self.logic.handle_key((13, "\r"))
        self.assertEqual(self.state.settings_view, "wifi_password")
        self.assertEqual(self.state.settings_wifi_status, "Wrong password")

    def test_escape_returns_to_network_list_without_rescan(self):
        self._open_password()
        scans_before = len(self.sysinfo.connect_calls)
        self.sysinfo.wifi_scan = lambda: self.fail("should not rescan")
        self.logic.handle_key((27, "\x1b"))
        self.assertEqual(self.state.settings_view, "wifi")
        self.assertEqual(len(self.sysinfo.connect_calls), scans_before)
        self.assertEqual([r[0] for r in self.state.settings_popup_rows],
                         ["HomeNet", "CoffeeShop", "Studio5G", "Rescan", "Back"])

    def test_delete_on_empty_password_returns_to_list(self):
        """B9/B10 are cursor keys now; DELETE on an empty field is the way out."""
        self._open_password()
        self.press(KEY_DELETE)
        self.assertEqual(self.state.settings_view, "wifi")

    def test_delete_with_text_edits_instead_of_leaving(self):
        self._open_password()
        self.type_text("ab")
        self.press(KEY_DELETE)
        self.assertEqual(self.state.settings_view, "wifi_password")
        self.assertEqual(self.state.settings_password, "a")

    def test_footswitch_typing_builds_the_password(self):
        self._open_password()
        self.press(2)                       # a
        self.press(KEY_SHIFT)
        self.press(3)                       # H
        self.press(1)                       # 0
        self.assertEqual(self.state.settings_password, "aH0")
        self.press(BUTTON_NUM_POWER)
        self.assertEqual(self.sysinfo.connect_calls, [("Studio5G", "aH0")])

    def test_keys_ignored_outside_password_view(self):
        self._open_wifi()
        self.logic.handle_key((ord("x"), "x"))
        self.assertEqual(self.state.settings_password, "")

    def test_rescan_row_rescans(self):
        self._open_wifi()
        self.sysinfo.networks = self.sysinfo.networks[:1]
        self.state.settings_index = 3  # "Rescan"
        self.press(9)
        self.assertEqual([r[0] for r in self.state.settings_popup_rows],
                         ["HomeNet", "Rescan", "Back"])


class SysinfoWifiTest(unittest.TestCase):
    """nmcli terse-output parsing and connect result mapping."""

    def setUp(self):
        from hardware import sysinfo
        self.sysinfo = sysinfo
        self.commands = []
        self.results = []
        self._original = sysinfo._run_result

        def fake_run(*args, timeout=5):
            self.commands.append(args)
            return self.results.pop(0) if self.results else (0, "", "")

        sysinfo._run_result = fake_run

    def tearDown(self):
        self.sysinfo._run_result = self._original

    def test_scan_parses_merges_and_sorts(self):
        self.results = [(0, "\n".join([
            r"*:HomeNet:82:WPA2",
            r":HomeNet:40:WPA2",       # weaker BSSID of the same SSID
            r":Cafe\: Guest:61:",      # escaped colon in the SSID, open
            r":Studio5G:47:WPA1 WPA2",
            r"::30:WPA2",              # hidden SSID: skipped
        ]), "")]
        networks = self.sysinfo.wifi_scan()
        self.assertEqual([n["ssid"] for n in networks],
                         ["HomeNet", "Cafe: Guest", "Studio5G"])
        home = networks[0]
        self.assertEqual(home, {"ssid": "HomeNet", "signal": 82,
                                "secured": True, "in_use": True})
        self.assertFalse(networks[1]["secured"])

    def test_scan_failure_returns_none(self):
        self.results = [(10, "", "Error: wifi is disabled")]
        self.assertIsNone(self.sysinfo.wifi_scan())

    def test_connect_success(self):
        self.results = [(0, "", ""),  # profile delete
                        (0, "Device 'wlan0' successfully activated.", "")]
        ok, message = self.sysinfo.wifi_connect("HomeNet", "secret99")
        self.assertTrue(ok)
        self.assertIn("HomeNet", message)
        connect = self.commands[1]
        self.assertIn("password", connect)
        self.assertIn("secret99", connect)

    def test_connect_open_network_sends_no_password(self):
        self.results = [(1, "", ""),  # profile lookup: no saved profile
                        (0, "", "")]
        self.sysinfo.wifi_connect("Cafe", None)
        joined = [c for c in self.commands if "wifi" in c and "connect" in c][0]
        self.assertNotIn("password", joined)
        self.assertNotIn("delete", [word for c in self.commands for word in c])

    def test_connect_wrong_password_maps_message(self):
        self.results = [(0, "", ""),
                        (4, "", "Error: Connection activation failed: "
                                "Secrets were required, but not provided."),
                        (0, "", "")]  # failed-profile cleanup
        ok, message = self.sysinfo.wifi_connect("HomeNet", "wrong")
        self.assertFalse(ok)
        self.assertEqual(message, "Wrong password")
        # The profile this call created gets deleted (as root — NM edits are
        # polkit-gated and the app has no login session).
        self.assertEqual(self.commands[-1],
                         ("sudo", "-n", "nmcli", "connection", "delete", "id",
                          "HomeNet"))


if __name__ == "__main__":
    unittest.main()
