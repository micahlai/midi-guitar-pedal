"""Milestone 12.5: palette references, menu names, presets, undo/redo."""

import copy
import tempfile
import unittest
from pathlib import Path

from config import loader, presets
from config.defaults import default_config
from config.model import resolve_color
from state.manager import StateManager
from web.server import (
    WebServer, install_config, set_menu_name, set_palette, validate_action,
)


def make_state():
    return StateManager(default_config())


class ResolveColorTest(unittest.TestCase):
    def test_literal_passthrough(self):
        self.assertEqual(resolve_color(default_config(), "#ABCDEF"), "#ABCDEF")

    def test_palette_reference(self):
        config = default_config()
        config["ui"]["color_palette"][3] = "#123456"
        self.assertEqual(resolve_color(config, "palette:3"), "#123456")

    def test_bad_reference_falls_back(self):
        self.assertEqual(resolve_color(default_config(), "palette:99"), "#303030")
        self.assertEqual(resolve_color(default_config(), None), "#303030")


class PaletteValidationTest(unittest.TestCase):
    def test_action_accepts_palette_ref(self):
        action = validate_action(
            {"type": "effect_cc", "midi_channel": 1, "cc_number": 20,
             "label": "X", "off_color": "palette:9", "on_color": "palette:0"},
            ("effect_cc",), secondary=False,
        )
        self.assertEqual(action["off_color"], "palette:9")
        self.assertEqual(action["on_color"], "palette:0")

    def test_action_rejects_out_of_range_ref(self):
        with self.assertRaises(ValueError):
            validate_action(
                {"type": "effect_cc", "midi_channel": 1, "cc_number": 20,
                 "label": "X", "off_color": "palette:10", "on_color": "#00FF00"},
                ("effect_cc",), secondary=False,
            )

    def test_set_palette(self):
        config = default_config()
        colors = ["#000001"] * 10
        result = set_palette(config, colors)
        self.assertEqual(result["colors"], colors)
        self.assertEqual(config["ui"]["color_palette"], colors)

    def test_set_palette_labels(self):
        config = default_config()
        labels = ["  Drive  ", "x" * 30] + [""] * 8
        result = set_palette(config, labels=labels)
        self.assertEqual(result["labels"][0], "Drive")
        self.assertEqual(result["labels"][1], "x" * 20)  # trimmed + capped
        self.assertEqual(config["ui"]["color_palette_labels"], result["labels"])
        # Colors untouched when only labels are sent.
        self.assertEqual(result["colors"], default_config()["ui"]["color_palette"])

    def test_set_palette_rejects_wrong_shape(self):
        config = default_config()
        with self.assertRaises(ValueError):
            set_palette(config, ["#000001"] * 9)
        with self.assertRaises(ValueError):
            set_palette(config, ["#000001"] * 9 + ["palette:1"])
        with self.assertRaises(ValueError):
            set_palette(config, labels=["ok"] * 9)
        with self.assertRaises(ValueError):
            set_palette(config, labels=["ok"] * 9 + [7])
        with self.assertRaises(ValueError):
            set_palette(config)


class MenuNameTest(unittest.TestCase):
    def test_set_and_trim(self):
        config = default_config()
        result = set_menu_name(config, 2, "  Worship Set  ")
        self.assertEqual(result, {"menu_id": 2, "name": "Worship Set"})
        self.assertEqual(config["menus"][1]["name"], "Worship Set")

    def test_empty_falls_back(self):
        config = default_config()
        self.assertEqual(set_menu_name(config, 3, "   ")["name"], "Menu 3")

    def test_unknown_menu(self):
        with self.assertRaises(ValueError):
            set_menu_name(default_config(), 7, "X")


class PresetFilesTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old_dir = loader.CONFIG_DIR
        loader.CONFIG_DIR = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(setattr, loader, "CONFIG_DIR", self._old_dir)

    def test_round_trip(self):
        config = default_config()
        config["menus"][0]["name"] = "Custom"
        presets.save_preset("Gig A", config)
        self.assertEqual([p["name"] for p in presets.list_presets()], ["Gig A"])
        loaded = presets.load_preset("Gig A")
        self.assertEqual(loaded["menus"][0]["name"], "Custom")
        self.assertEqual(loaded["preset_name"], "Gig A")

    def test_bad_names_rejected(self):
        for bad in ("", "../evil", "a/b", ".hidden", "x" * 41, 5, None):
            with self.assertRaises(ValueError):
                presets.validate_preset_name(bad)

    def test_load_missing(self):
        with self.assertRaises(ValueError):
            presets.load_preset("nope")

    def test_delete(self):
        presets.save_preset("Gone", default_config())
        presets.delete_preset("Gone")
        self.assertEqual(presets.list_presets(), [])

    def test_import_validates_version(self):
        with self.assertRaises(ValueError):
            presets.import_preset("bad", {"version": 999})
        good = default_config()
        presets.import_preset("ok", good)
        self.assertEqual([p["name"] for p in presets.list_presets()], ["ok"])

    def test_new_preset_config(self):
        config = presets.new_preset_config("Fresh")
        self.assertEqual(config["preset_name"], "Fresh")
        self.assertEqual(config["version"], default_config()["version"])


class InstallConfigTest(unittest.TestCase):
    def test_in_place_and_expression_guard(self):
        state = make_state()
        original = state.config  # modules keep this reference
        state.expression_mode = (1, 6, "primary")  # B6 VOLUME in defaults
        new = default_config()
        new["menus"][0]["slots"]["6"]["primary"] = {
            "type": "nothing", "label": "", "color": "#1A1A1A",
        }
        install_config(state, new)
        self.assertIs(state.config, original)
        self.assertIsNone(state.expression_mode)
        self.assertEqual(state.config["menus"][0]["slots"]["6"]["primary"]["type"], "nothing")

    def test_valid_expression_mode_survives(self):
        state = make_state()
        state.expression_mode = (1, 6, "primary")
        install_config(state, default_config())
        self.assertEqual(state.expression_mode, (1, 6, "primary"))


class UndoRedoTest(unittest.TestCase):
    def setUp(self):
        self.state = make_state()
        self.saves = []
        self.web = WebServer(self.state, save=self.saves.append)

    def edit_label(self, label):
        action = copy.deepcopy(self.state.config["menus"][0]["slots"]["2"]["primary"])
        action["label"] = label
        self.web.edit_primary({"menu_id": 1, "button_num": 2, "action": action})

    def current_label(self):
        return self.state.config["menus"][0]["slots"]["2"]["primary"]["label"]

    def test_undo_redo_cycle(self):
        self.edit_label("ONE")
        self.edit_label("TWO")
        self.assertEqual(self.current_label(), "TWO")
        self.web.undo({})
        self.assertEqual(self.current_label(), "ONE")
        self.web.undo({})
        self.assertEqual(self.current_label(), "DELAY")
        self.web.redo({})
        self.assertEqual(self.current_label(), "ONE")
        self.web.redo({})
        self.assertEqual(self.current_label(), "TWO")

    def test_empty_stacks_raise(self):
        with self.assertRaises(ValueError):
            self.web.undo({})
        with self.assertRaises(ValueError):
            self.web.redo({})

    def test_new_edit_clears_redo(self):
        self.edit_label("ONE")
        self.web.undo({})
        self.edit_label("THREE")
        with self.assertRaises(ValueError):
            self.web.redo({})

    def test_failed_edit_restores_and_adds_no_history(self):
        with self.assertRaises(ValueError):
            self.web.edit_primary({"menu_id": 1, "button_num": 2, "action": {"type": "bogus"}})
        self.assertEqual(self.current_label(), "DELAY")
        with self.assertRaises(ValueError):
            self.web.undo({})

    def test_settings_and_menu_edits_are_undoable(self):
        self.web.edit_menu({"menu_id": 1, "name": "Renamed"})
        self.web.edit_palette({"colors": ["#010101"] * 10})
        self.assertEqual(self.state.config["menus"][0]["name"], "Renamed")
        self.web.undo({})
        self.assertEqual(self.state.config["ui"]["color_palette"][0], "#00FF66")
        self.web.undo({})
        self.assertEqual(self.state.config["menus"][0]["name"], "Menu 1")

    def test_preset_name_setting(self):
        self.web.edit_settings({"preset_name": "My Rig"})
        self.assertEqual(self.state.config["preset_name"], "My Rig")


class PresetEndpointsTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old_dir = loader.CONFIG_DIR
        loader.CONFIG_DIR = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(setattr, loader, "CONFIG_DIR", self._old_dir)
        self.state = make_state()
        self.web = WebServer(self.state, save=lambda cfg: None)

    def test_save_load_new_cycle(self):
        self.state.config["menus"][0]["name"] = "Edited"
        self.web.preset_save({"name": "Rig"})
        self.assertEqual(self.state.config["preset_name"], "Rig")

        self.web.preset_new({"name": "Blank"})
        self.assertEqual(self.state.config["preset_name"], "Blank")
        self.assertEqual(self.state.config["menus"][0]["name"], "Menu 1")

        result = self.web.preset_load({"name": "Rig"})
        self.assertEqual(self.state.config["menus"][0]["name"], "Edited")
        self.assertIs(result["config"], self.state.config)

        # Loading a preset is undoable.
        self.web.undo({})
        self.assertEqual(self.state.config["preset_name"], "Blank")

    def test_load_clears_stale_expression_mode(self):
        self.web.preset_save({"name": "HasExp"})
        self.state.expression_mode = (1, 6, "primary")
        self.web.preset_new({"name": "Empty"})
        # Default config still has B6 as expression, so mode survives; force
        # a stale one instead.
        self.state.expression_mode = (2, 3, "primary")
        self.web.preset_load({"name": "HasExp"})
        self.assertIsNone(self.state.expression_mode)


if __name__ == "__main__":
    unittest.main()
