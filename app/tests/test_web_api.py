"""Tests for the Milestone 11 web server: slot editing logic + HTTP API."""

import json
import unittest
import urllib.request

from config.defaults import default_config
from state.manager import StateManager
from web.server import WebServer, set_primary_action


def make_state() -> StateManager:
    return StateManager(default_config())


class SetPrimaryActionTests(unittest.TestCase):
    def test_type_change_installs_fresh_template(self):
        state = make_state()
        slot = set_primary_action(state, 1, 2, "program_change", "PIANO")
        self.assertEqual(slot["primary"]["type"], "program_change")
        self.assertEqual(slot["primary"]["label"], "PIANO")
        self.assertIn("program_number", slot["primary"])
        self.assertNotIn("cc_number", slot["primary"])

    def test_same_type_edit_preserves_tuned_fields(self):
        state = make_state()
        # Default B1 is effect_cc with cc_number 21.
        slot = set_primary_action(state, 1, 1, "effect_cc", "CRUNCH")
        self.assertEqual(slot["primary"]["cc_number"], 21)
        self.assertEqual(slot["primary"]["label"], "CRUNCH")

    def test_creates_slot_in_empty_menu(self):
        state = make_state()
        slot = set_primary_action(state, 3, 7, "action_cc", "TAP")
        self.assertIs(slot, state.config["menus"][2]["slots"]["7"])
        self.assertEqual(slot["primary"]["type"], "action_cc")
        self.assertEqual(
            slot["primary"]["midi_channel"],
            state.config["midi"]["default_channel"],
        )

    def test_label_is_trimmed_and_capped(self):
        state = make_state()
        slot = set_primary_action(state, 1, 3, "action_cc", "  " + "X" * 40)
        self.assertEqual(slot["primary"]["label"], "X" * 24)

    def test_rejects_bad_input(self):
        state = make_state()
        with self.assertRaises(ValueError):
            set_primary_action(state, 5, 1, "nothing", "")
        with self.assertRaises(ValueError):
            set_primary_action(state, 1, 10, "nothing", "")
        with self.assertRaises(ValueError):
            set_primary_action(state, 1, 1, "warp_drive", "")
        with self.assertRaises(ValueError):
            set_primary_action(state, "1", 1, "nothing", "")
        with self.assertRaises(ValueError):
            set_primary_action(state, 1, 1, "nothing", None)

    def test_clears_active_expression_mode_on_type_change(self):
        state = make_state()
        state.expression_mode = (1, 6, "primary")  # default B6 = VOLUME pot
        set_primary_action(state, 1, 6, "effect_cc", "CHORUS")
        self.assertIsNone(state.expression_mode)

    def test_keeps_expression_mode_for_other_slots_and_same_type(self):
        state = make_state()
        state.expression_mode = (1, 6, "primary")
        set_primary_action(state, 1, 7, "nothing", "")
        self.assertEqual(state.expression_mode, (1, 6, "primary"))
        set_primary_action(state, 1, 6, "expression_pedal", "VOL")
        self.assertEqual(state.expression_mode, (1, 6, "primary"))


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

    def test_get_config(self):
        with urllib.request.urlopen(self.base + "/api/config") as res:
            self.assertEqual(res.status, 200)
            config = json.loads(res.read())
        self.assertEqual(len(config["menus"]), 4)

    def test_get_index(self):
        with urllib.request.urlopen(self.base + "/") as res:
            self.assertEqual(res.status, 200)
            self.assertIn(b"MIDI Foot Controller", res.read())

    def test_post_slot_applies_and_saves(self):
        status, body = self._post(
            "/api/slot",
            {"menu_id": 2, "button_num": 4, "type": "program_change", "label": "VERSE"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["slot"]["primary"]["label"], "VERSE")
        self.assertEqual(
            self.state.config["menus"][1]["slots"]["4"]["primary"]["type"],
            "program_change",
        )
        self.assertEqual(len(self.saved), 1)
        self.assertIs(self.saved[0], self.state.config)

    def test_post_slot_rejects_invalid(self):
        status, body = self._post(
            "/api/slot", {"menu_id": 1, "button_num": 1, "type": "bogus", "label": ""}
        )
        self.assertEqual(status, 400)
        self.assertIn("bogus", body["error"])
        self.assertEqual(self.saved, [])

    def test_unknown_paths_are_404(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(self.base + "/api/nope")
        self.assertEqual(ctx.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
