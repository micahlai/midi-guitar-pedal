"""Tests for the web server (Milestones 11-12): validation, slot edits,
settings, and the HTTP API."""

import json
import unittest
import urllib.error
import urllib.request

from config.defaults import default_config
from state.manager import StateManager
from web.server import (
    WebServer,
    apply_settings,
    remove_secondary,
    set_primary,
    set_secondary,
    validate_action,
)


def make_state() -> StateManager:
    return StateManager(default_config())


def effect_action(**overrides) -> dict:
    action = {
        "type": "effect_cc", "midi_channel": 1, "cc_number": 30,
        "off_color": "#303030", "on_color": "#00ff66",
        "label": "FUZZ", "image_asset_id": None,
    }
    action.update(overrides)
    return action


def expression_action(**overrides) -> dict:
    action = {
        "type": "expression_pedal", "midi_channel": 2, "cc_number": 11,
        "color": "#CC66FF", "value_min": 10, "value_max": 120,
        "reverse": True, "has_home": True, "home_value": 5,
        "label": "WAH", "image_asset_id": None,
    }
    action.update(overrides)
    return action


class ValidateActionTests(unittest.TestCase):
    def test_normalizes_effect_cc(self):
        action = validate_action(
            effect_action(label="  FUZZ  ", extra_junk=True), ("effect_cc",), allow_image=True
        )
        self.assertEqual(action["label"], "FUZZ")
        self.assertEqual(action["on_color"], "#00FF66")  # uppercased
        self.assertNotIn("extra_junk", action)
        self.assertIn("image_asset_id", action)

    def test_expression_fields_round_trip(self):
        action = validate_action(expression_action(), ("expression_pedal",), allow_image=True)
        self.assertEqual(action["value_min"], 10)
        self.assertTrue(action["reverse"])
        self.assertEqual(action["home_value"], 5)

    def test_secondary_drops_image(self):
        action = validate_action(effect_action(), ("effect_cc",), allow_image=False)
        self.assertNotIn("image_asset_id", action)

    def test_rejects_bad_fields(self):
        bad = [
            effect_action(midi_channel=0),
            effect_action(midi_channel=True),
            effect_action(cc_number=128),
            effect_action(on_color="green"),
            effect_action(type="expression_pedal"),  # not in allowed list
            expression_action(reverse="yes"),
            "not a dict",
        ]
        for raw in bad:
            with self.assertRaises(ValueError, msg=repr(raw)):
                allowed = ("effect_cc",) if isinstance(raw, dict) else ("effect_cc",)
                validate_action(raw, allowed, allow_image=True)


class SlotEditTests(unittest.TestCase):
    def test_set_primary_replaces_action(self):
        state = make_state()
        slot = set_primary(state, 1, 2, effect_action(cc_number=40))
        self.assertEqual(slot["primary"]["cc_number"], 40)
        self.assertIs(slot, state.config["menus"][0]["slots"]["2"])

    def test_set_primary_clears_active_expression_mode(self):
        state = make_state()
        state.expression_mode = (1, 6, "primary")
        set_primary(state, 1, 6, effect_action())
        self.assertIsNone(state.expression_mode)
        # Replacing with another expression action keeps the mode.
        state.expression_mode = (1, 7, "primary")
        set_primary(state, 1, 7, expression_action())
        self.assertEqual(state.expression_mode, (1, 7, "primary"))

    def test_set_secondary_requires_primary(self):
        state = make_state()
        with self.assertRaises(ValueError):
            set_secondary(state, 2, 1, 1.5, effect_action())

    def test_set_secondary_and_remove(self):
        state = make_state()
        slot = set_secondary(state, 1, 2, 2.5, effect_action(label="BOOST"))
        self.assertTrue(slot["secondary"]["enabled"])
        self.assertEqual(slot["secondary"]["hold_seconds"], 2.5)
        self.assertEqual(slot["secondary"]["action"]["label"], "BOOST")
        slot = remove_secondary(state, 1, 2)
        self.assertNotIn("secondary", slot)

    def test_secondary_rejects_expression_type(self):
        state = make_state()
        with self.assertRaises(ValueError):
            set_secondary(state, 1, 2, 1.5, expression_action())

    def test_remove_secondary_clears_its_expression_mode(self):
        state = make_state()
        state.expression_mode = (1, 1, "secondary")
        remove_secondary(state, 1, 1)
        self.assertIsNone(state.expression_mode)

    def test_rejects_bad_slot_coordinates(self):
        state = make_state()
        for menu_id, button_num in ((5, 1), ("1", 1), (1, 0), (1, 10), (1, "3")):
            with self.assertRaises(ValueError):
                set_primary(state, menu_id, button_num, effect_action())


class ApplySettingsTests(unittest.TestCase):
    def test_applies_all_settings(self):
        config = default_config()
        applied = apply_settings(config, {
            "shift_hold_seconds": 3.0,
            "secondary_hold_default_seconds": 1.0,
            "expression_panel_width_ratio": 0.2,
        })
        self.assertEqual(config["buttons"]["shift_hold_seconds"], 3.0)
        self.assertEqual(config["buttons"]["secondary_hold_default_seconds"], 1.0)
        self.assertEqual(config["ui"]["expression_panel_width_ratio"], 0.2)
        self.assertEqual(len(applied), 3)

    def test_rejects_out_of_range_and_empty(self):
        config = default_config()
        with self.assertRaises(ValueError):
            apply_settings(config, {"shift_hold_seconds": 0.1})
        with self.assertRaises(ValueError):
            apply_settings(config, {"expression_panel_width_ratio": 0.5})
        with self.assertRaises(ValueError):
            apply_settings(config, {"unknown_setting": 1})
        # Nothing partially applied.
        self.assertEqual(config["buttons"]["shift_hold_seconds"], 2.0)


class WebServerHttpTests(unittest.TestCase):
    def setUp(self):
        self.state = make_state()
        self.state.config["web"] = {"enabled": True, "port": 0}
        self.saved = []
        self.server = WebServer(self.state, save=self.saved.append)
        self.server.start()
        self.assertIsNotNone(self.server.port)
        self.base = f"http://127.0.0.1:{self.server.port}"

    def tearDown(self):
        self.server.stop()

    def _post(self, path, payload):
        req = urllib.request.Request(
            self.base + path,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req) as res:
                return res.status, json.loads(res.read())
        except urllib.error.HTTPError as err:
            return err.code, json.loads(err.read())

    def test_get_config_and_index(self):
        with urllib.request.urlopen(self.base + "/api/config") as res:
            self.assertEqual(len(json.loads(res.read())["menus"]), 4)
        with urllib.request.urlopen(self.base + "/") as res:
            self.assertIn(b"MIDI Foot Controller", res.read())

    def test_get_status(self):
        self.state.expression_mode = (1, 6, "primary")
        self.state.expression_value = 0.5
        with urllib.request.urlopen(self.base + "/api/status") as res:
            status = json.loads(res.read())
        self.assertEqual(status["expression_mode"], [1, 6, "primary"])
        self.assertEqual(status["current_menu"], 1)

    def test_primary_secondary_lifecycle(self):
        status, body = self._post("/api/slot/primary", {
            "menu_id": 2, "button_num": 4, "action": effect_action(label="VERSE"),
        })
        self.assertEqual(status, 200)
        status, body = self._post("/api/slot/secondary", {
            "menu_id": 2, "button_num": 4, "hold_seconds": 2.0,
            "action": effect_action(label="CHORUS"),
        })
        self.assertEqual(status, 200)
        self.assertEqual(body["slot"]["secondary"]["action"]["label"], "CHORUS")
        status, body = self._post("/api/slot/secondary/remove",
                                  {"menu_id": 2, "button_num": 4})
        self.assertEqual(status, 200)
        self.assertNotIn("secondary", body["slot"])
        self.assertEqual(len(self.saved), 3)

    def test_settings_endpoint(self):
        status, body = self._post("/api/settings", {"shift_hold_seconds": 4.0})
        self.assertEqual(status, 200)
        self.assertEqual(body["settings"], {"shift_hold_seconds": 4.0})
        self.assertEqual(self.state.config["buttons"]["shift_hold_seconds"], 4.0)

    def test_validation_errors_are_400(self):
        status, body = self._post("/api/slot/primary", {
            "menu_id": 1, "button_num": 1, "action": effect_action(cc_number=999),
        })
        self.assertEqual(status, 400)
        self.assertIn("cc_number", body["error"])
        self.assertEqual(self.saved, [])


if __name__ == "__main__":
    unittest.main()
