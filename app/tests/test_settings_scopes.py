"""Settings scopes: preset-scoped settings travel with preset files while
device-scoped settings stay on the device, plus validation of the full
settings surface exposed by the web Settings tab."""

import json
import tempfile
import unittest
import urllib.request
from pathlib import Path

from config import loader, presets
from config.defaults import (
    copy_device_settings, default_config, strip_device_settings,
)
from state.manager import StateManager
from web.server import WebServer, apply_settings


class ScopeHelpersTest(unittest.TestCase):
    def test_strip_removes_device_keys_only(self):
        config = default_config()
        strip_device_settings(config)
        self.assertNotIn("name", config["device"])
        self.assertNotIn("port", config["web"])
        self.assertNotIn("usb_enabled", config["midi"])
        self.assertNotIn("debounce_ms", config["buttons"])
        self.assertNotIn("poll_interval_ms", config["expression"])
        self.assertNotIn("screen_width", config["ui"])
        # Preset-scoped values stay.
        self.assertIn("shift_hold_seconds", config["buttons"])
        self.assertIn("program_display_base", config["midi"])
        self.assertIn("theme", config["ui"])
        self.assertIn("menus", config)

    def test_copy_overlays_device_keys(self):
        source = default_config()
        source["device"]["name"] = "My Pedal"
        source["midi"]["ble_enabled"] = False
        source["buttons"]["debounce_ms"] = 50
        target = default_config()
        target["buttons"]["shift_hold_seconds"] = 4.0
        copy_device_settings(source, target)
        self.assertEqual(target["device"]["name"], "My Pedal")
        self.assertFalse(target["midi"]["ble_enabled"])
        self.assertEqual(target["buttons"]["debounce_ms"], 50)
        # Preset-scoped values in the target are untouched.
        self.assertEqual(target["buttons"]["shift_hold_seconds"], 4.0)


class PresetScopeTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old_dir = loader.CONFIG_DIR
        loader.CONFIG_DIR = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(setattr, loader, "CONFIG_DIR", self._old_dir)
        self.state = StateManager(default_config())
        self.web = WebServer(self.state, save=lambda cfg: None)

    def test_preset_file_has_no_device_settings(self):
        presets.save_preset("Rig", self.state.config)
        raw = json.loads((Path(self._tmp.name) / "presets" / "Rig.json").read_text())
        self.assertNotIn("name", raw["device"])
        self.assertNotIn("port", raw["web"])
        self.assertNotIn("debounce_ms", raw["buttons"])
        self.assertIn("shift_hold_seconds", raw["buttons"])
        self.assertIn("menus", raw)

    def test_preset_load_keeps_device_settings(self):
        self.state.config["buttons"]["shift_hold_seconds"] = 3.0
        self.web.preset_save({"name": "Rig"})
        # Device-level changes made after the preset was saved…
        self.web.edit_settings({
            "device_name": "Board B", "ble_enabled": False, "debounce_ms": 60,
        })
        # …and a preset-level change that the load should revert.
        self.web.edit_settings({"shift_hold_seconds": 5.0})
        self.web.preset_load({"name": "Rig"})
        self.assertEqual(self.state.config["buttons"]["shift_hold_seconds"], 3.0)
        self.assertEqual(self.state.config["device"]["name"], "Board B")
        self.assertFalse(self.state.config["midi"]["ble_enabled"])
        self.assertEqual(self.state.config["buttons"]["debounce_ms"], 60)

    def test_preset_new_keeps_device_settings(self):
        self.web.edit_settings({"device_name": "Board B", "web_port": 9090})
        self.web.preset_new({"name": "Blank"})
        self.assertEqual(self.state.config["device"]["name"], "Board B")
        self.assertEqual(self.state.config["web"]["port"], 9090)

    def test_export_strips_device_settings(self):
        self.state.config["web"]["port"] = 0  # ephemeral test port
        self.web.start()
        self.addCleanup(self.web.stop)
        with urllib.request.urlopen(
                f"http://127.0.0.1:{self.web.port}/api/preset/export") as res:
            exported = json.loads(res.read())
        self.assertNotIn("name", exported["device"])
        self.assertNotIn("usb_enabled", exported["midi"])
        self.assertIn("menus", exported)
        # The live config itself is untouched by the export.
        self.assertIn("usb_enabled", self.state.config["midi"])


class ApplySettingsTest(unittest.TestCase):
    def setUp(self):
        self.config = default_config()

    def test_preset_scoped_fields(self):
        applied = apply_settings(self.config, {
            "default_channel": 4,
            "theme_background": "#101010",
            "theme_text": "#eeeeee",
        })
        self.assertEqual(self.config["midi"]["default_channel"], 4)
        self.assertEqual(self.config["ui"]["theme"]["background"], "#101010")
        self.assertEqual(self.config["ui"]["theme"]["text"], "#EEEEEE")
        self.assertEqual(applied["theme_text"], "#EEEEEE")

    def test_device_scoped_fields(self):
        apply_settings(self.config, {
            "device_name": "  Stage Board  ",
            "web_port": 9000,
            "debounce_ms": 40,
            "power_double_press_ms": 500,
            "power_hold_seconds": 4.0,
            "show_tempo": False,
            "detect_enabled": False,
            "send_deadband": 2,
            "poll_interval_ms": 20,
            "return_alpha": 0.2,
            "return_interval_ms": 40,
            "return_stop_threshold": 1.0,
        })
        self.assertEqual(self.config["device"]["name"], "Stage Board")
        self.assertEqual(self.config["web"]["port"], 9000)
        self.assertEqual(self.config["buttons"]["debounce_ms"], 40)
        self.assertEqual(self.config["buttons"]["power_hold_seconds"], 4.0)
        self.assertFalse(self.config["ui"]["show_tempo"])
        self.assertFalse(self.config["expression"]["detect_enabled"])
        self.assertEqual(self.config["expression"]["poll_interval_ms"], 20)
        self.assertEqual(self.config["expression"]["return_alpha"], 0.2)

    def test_invalid_values_rejected(self):
        bad = [
            {"default_channel": 17},
            {"theme_background": "palette:1"},  # theme colors are literal only
            {"theme_text": "red"},
            {"device_name": "   "},
            {"device_name": 7},
            {"web_port": 80},
            {"web_port": "8080"},
            {"debounce_ms": 300},
            {"power_double_press_ms": 50},
            {"power_hold_seconds": 60},
            {"detect_enabled": "yes"},
            {"show_tempo": "off"},
            {"send_deadband": -1},
            {"poll_interval_ms": 1},
            {"return_alpha": 0.0},
            {"return_stop_threshold": 9},
        ]
        for payload in bad:
            with self.assertRaises(ValueError, msg=payload):
                apply_settings(default_config(), payload)


if __name__ == "__main__":
    unittest.main()
