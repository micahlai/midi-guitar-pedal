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
    swap_menus,
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
        "off_color": "#303030", "on_color": "#CC66FF",
        "value_min": 10, "value_max": 120,
        "reverse": True, "has_home": True, "home_value": 5,
        "label": "WAH", "image_asset_id": None,
    }
    action.update(overrides)
    return action


class ValidateActionTests(unittest.TestCase):
    def test_normalizes_effect_cc(self):
        action = validate_action(
            effect_action(label="  FUZZ  ", extra_junk=True), ("effect_cc",), secondary=False
        )
        self.assertEqual(action["label"], "FUZZ")
        self.assertEqual(action["on_color"], "#00FF66")  # uppercased
        self.assertNotIn("extra_junk", action)
        self.assertIn("image_asset_id", action)
        self.assertIn("off_color", action)

    def test_expression_fields_round_trip(self):
        action = validate_action(expression_action(), ("expression_pedal",), secondary=False)
        self.assertEqual(action["value_min"], 10)
        self.assertTrue(action["reverse"])
        self.assertEqual(action["home_value"], 5)

    def test_action_cc_selection_group(self):
        action = validate_action(
            effect_action(type="action_cc", selection_group=2),
            ("action_cc",), secondary=False)
        self.assertEqual(action["selection_group"], 2)
        # Absent -> ungrouped (0), i.e. the momentary behavior it has always had.
        action = validate_action(
            effect_action(type="action_cc"), ("action_cc",), secondary=False)
        self.assertEqual(action["selection_group"], 0)
        for bad in (6, -1, "1", True):
            with self.assertRaises(ValueError, msg=bad):
                validate_action(effect_action(type="action_cc", selection_group=bad),
                                ("action_cc",), secondary=False)
        # Only action_cc latches; the field is not carried on other types.
        action = validate_action(
            effect_action(type="effect_cc", selection_group=2),
            ("effect_cc",), secondary=False)
        self.assertNotIn("selection_group", action)

    def test_action_cc_color_duration_secondary_only(self):
        raw = effect_action(type="action_cc", color_duration=2.5)
        secondary = validate_action(raw, ("action_cc",), secondary=True)
        self.assertEqual(secondary["color_duration"], 2.5)
        primary = validate_action(raw, ("action_cc",), secondary=False)
        self.assertNotIn("color_duration", primary)
        # Missing -> default 1.0; out of range -> rejected.
        secondary = validate_action(
            effect_action(type="action_cc"), ("action_cc",), secondary=True)
        self.assertEqual(secondary["color_duration"], 1.0)
        with self.assertRaises(ValueError):
            validate_action(effect_action(type="action_cc", color_duration=0),
                            ("action_cc",), secondary=True)

    def test_secondary_drops_image_and_off_color(self):
        action = validate_action(effect_action(), ("effect_cc",), secondary=True)
        self.assertNotIn("image_asset_id", action)
        self.assertNotIn("off_color", action)
        self.assertEqual(action["on_color"], "#00FF66")

    def test_secondary_needs_no_off_color(self):
        raw = effect_action()
        del raw["off_color"]
        action = validate_action(raw, ("effect_cc",), secondary=True)
        self.assertEqual(action["type"], "effect_cc")
        # But a primary does need one.
        with self.assertRaises(ValueError):
            validate_action(raw, ("effect_cc",), secondary=False)

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
                validate_action(raw, ("effect_cc",), secondary=False)


class ProgramDisplayBaseTests(unittest.TestCase):
    def pc_action(self, number):
        return {
            "type": "program_change", "midi_channel": 1, "program_number": number,
            "off_color": "#303030", "on_color": "#3399FF",
            "label": "PATCH", "image_asset_id": None,
        }

    def test_base1_rejects_zero_and_allows_128(self):
        with self.assertRaises(ValueError):
            validate_action(self.pc_action(0), ("program_change",), False, pc_base=1)
        action = validate_action(self.pc_action(128), ("program_change",), False, pc_base=1)
        self.assertEqual(action["program_number"], 128)

    def test_base0_rejects_128_and_allows_zero(self):
        with self.assertRaises(ValueError):
            validate_action(self.pc_action(128), ("program_change",), False, pc_base=0)
        action = validate_action(self.pc_action(0), ("program_change",), False, pc_base=0)
        self.assertEqual(action["program_number"], 0)

    def test_set_primary_uses_config_base(self):
        state = make_state()  # default base is 1
        with self.assertRaises(ValueError):
            set_primary(state, 1, 4, self.pc_action(0))
        state.config["midi"]["program_display_base"] = 0
        set_primary(state, 1, 4, self.pc_action(0))

    def test_base_change_shifts_all_program_numbers(self):
        config = default_config()  # base 1; RHYTHM=1, LEAD=2, SOLO secondary=3
        apply_settings(config, {"program_display_base": 0})
        slots = config["menus"][0]["slots"]
        self.assertEqual(slots["4"]["primary"]["program_number"], 0)
        self.assertEqual(slots["5"]["primary"]["program_number"], 1)
        self.assertEqual(slots["1"]["secondary"]["action"]["program_number"], 2)
        # Non-PC actions untouched.
        self.assertEqual(slots["2"]["primary"]["cc_number"], 22)
        # And back up again.
        apply_settings(config, {"program_display_base": 1})
        self.assertEqual(slots["4"]["primary"]["program_number"], 1)
        self.assertEqual(slots["1"]["secondary"]["action"]["program_number"], 3)

    def test_same_base_is_a_no_op_shift(self):
        config = default_config()
        apply_settings(config, {"program_display_base": 1})
        self.assertEqual(config["menus"][0]["slots"]["4"]["primary"]["program_number"], 1)

    def test_rejects_invalid_base(self):
        with self.assertRaises(ValueError):
            apply_settings(default_config(), {"program_display_base": 2})


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

    def test_secondary_accepts_expression_type(self):
        state = make_state()
        slot = set_secondary(state, 1, 2, 1.5, expression_action())
        action = slot["secondary"]["action"]
        self.assertEqual(action["type"], "expression_pedal")
        self.assertNotIn("off_color", action)
        self.assertNotIn("image_asset_id", action)

    def test_secondary_rejects_nothing_type(self):
        state = make_state()
        with self.assertRaises(ValueError):
            set_secondary(state, 1, 2, 1.5, {"type": "nothing", "label": ""})

    def test_remove_secondary_clears_its_expression_mode(self):
        state = make_state()
        state.expression_mode = (1, 1, "secondary")
        remove_secondary(state, 1, 1)
        self.assertIsNone(state.expression_mode)

    def test_swap_menus_swaps_slots_and_names(self):
        state = make_state()
        set_primary(state, 1, 3, effect_action(label="ONE", cc_number=41))
        set_primary(state, 2, 5, effect_action(label="TWO", cc_number=42))
        state.config["menus"][0]["name"] = "Rhythm"
        state.config["menus"][1]["name"] = "Lead"

        result = swap_menus(state, 1, 2)

        m1, m2 = state.config["menus"][0], state.config["menus"][1]
        self.assertEqual(m1["id"], 1)  # ids stay put (physical position)
        self.assertEqual(m2["id"], 2)
        self.assertEqual(m1["name"], "Lead")
        self.assertEqual(m2["name"], "Rhythm")
        # The button assignments moved with their menu.
        self.assertNotIn("3", m1["slots"])
        self.assertEqual(m1["slots"]["5"]["primary"]["label"], "TWO")
        self.assertEqual(m2["slots"]["3"]["primary"]["label"], "ONE")
        self.assertIn({"id": 1, "name": "Lead"}, result["menus"])

    def test_swap_menus_clears_affected_expression_mode(self):
        state = make_state()
        state.expression_mode = (1, 6, "primary")
        swap_menus(state, 1, 2)
        self.assertIsNone(state.expression_mode)

    def test_swap_menus_keeps_unaffected_expression_mode(self):
        state = make_state()
        state.expression_mode = (3, 6, "primary")
        swap_menus(state, 1, 2)
        self.assertEqual(state.expression_mode, (3, 6, "primary"))

    def test_swap_menus_rejects_self_and_unknown(self):
        state = make_state()
        with self.assertRaises(ValueError):
            swap_menus(state, 1, 1)
        with self.assertRaises(ValueError):
            swap_menus(state, 1, 99)

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

    def test_menu_swap_endpoint_and_undo(self):
        self._post("/api/slot/primary", {
            "menu_id": 1, "button_num": 2, "action": effect_action(label="A", cc_number=44),
        })
        status, body = self._post("/api/menu/swap", {"menu_id": 1, "other_id": 3})
        self.assertEqual(status, 200)
        menus = {m["id"]: m for m in body["config"]["menus"]}
        self.assertEqual(menus[3]["slots"]["2"]["primary"]["label"], "A")
        self.assertNotIn("2", menus[1]["slots"])
        # Swap is undoable like any other mutation.
        status, body = self._post("/api/undo", {})
        self.assertEqual(status, 200)
        menus = {m["id"]: m for m in body["config"]["menus"]}
        self.assertEqual(menus[1]["slots"]["2"]["primary"]["label"], "A")

    def test_menu_swap_self_is_400(self):
        status, body = self._post("/api/menu/swap", {"menu_id": 1, "other_id": 1})
        self.assertEqual(status, 400)
        self.assertIn("itself", body["error"])


class DefaultExpressionTests(unittest.TestCase):
    """is_default on expression assignments: the pot's fallback mode when no
    expression button is selected; at most one config-wide."""

    def test_validation_defaults_false_accepts_true_rejects_junk(self):
        action = validate_action(expression_action(), ("expression_pedal",), secondary=False)
        self.assertFalse(action["is_default"])
        action = validate_action(
            expression_action(is_default=True), ("expression_pedal",), secondary=False)
        self.assertTrue(action["is_default"])
        with self.assertRaises(ValueError):
            validate_action(
                expression_action(is_default="yes"), ("expression_pedal",), secondary=False)

    def test_only_one_default_config_wide(self):
        from config.model import find_default_expression, get_primary
        state = make_state()
        set_primary(state, 1, 6, expression_action(is_default=True))
        self.assertEqual(find_default_expression(state.config), (1, 6, "primary"))
        set_primary(state, 2, 3, expression_action(cc_number=12, is_default=True))
        self.assertEqual(find_default_expression(state.config), (2, 3, "primary"))
        self.assertFalse(get_primary(state.config, 1, 6)["is_default"])

    def test_secondary_default_clears_primary_default(self):
        from config.model import find_default_expression, get_primary
        state = make_state()
        set_primary(state, 1, 6, expression_action(is_default=True))
        set_primary(state, 1, 7, effect_action())
        set_secondary(state, 1, 7, 1.5, expression_action(cc_number=12, is_default=True))
        self.assertEqual(find_default_expression(state.config), (1, 7, "secondary"))
        self.assertFalse(get_primary(state.config, 1, 6)["is_default"])

    def test_pot_falls_back_to_default_when_no_mode_selected(self):
        state = make_state()
        set_primary(state, 2, 4, expression_action(is_default=True))
        state.config_version += 1  # web _mutate does this after every edit
        self.assertIsNone(state.expression_mode)
        self.assertEqual(state.effective_expression_mode(), (2, 4, "primary"))
        self.assertEqual(state.get_expression_action()["cc_number"], 11)
        # An explicitly selected mode wins over the default.
        set_primary(state, 1, 5, expression_action(cc_number=22))
        state.config_version += 1
        state.expression_mode = (1, 5, "primary")
        self.assertEqual(state.effective_expression_mode(), (1, 5, "primary"))
        self.assertEqual(state.get_expression_action()["cc_number"], 22)

    def test_no_default_means_no_fallback(self):
        state = make_state()
        self.assertIsNone(state.effective_expression_mode())
        self.assertIsNone(state.get_expression_action())


if __name__ == "__main__":
    unittest.main()
