"""Tests for the slot status color rules and the color-model migration."""

import unittest
from unittest.mock import patch

from config.defaults import default_config
from config.loader import _normalize_colors
from state.manager import StateManager
from ui.renderer import UiRenderer


def make_renderer():
    state = StateManager(default_config())
    return UiRenderer(state), state


def get_slot(state, button_num):
    return state.config["menus"][0]["slots"][str(button_num)]


class SlotStatusColorTests(unittest.TestCase):
    # Default B1: primary effect_cc DRIVE (ch1 note21, on #00FF66,
    # off #303030) + secondary program_change SOLO (program 3, on #3399FF).

    def test_off_when_nothing_active(self):
        renderer, state = make_renderer()
        self.assertEqual(renderer._slot_status_color(get_slot(state, 1), 1), "#303030")

    def test_primary_on_color_when_effect_active(self):
        renderer, state = make_renderer()
        state.effect_states[(1, 21)] = True
        self.assertEqual(renderer._slot_status_color(get_slot(state, 1), 1), "#00FF66")

    def test_secondary_on_color_when_patch_active(self):
        renderer, state = make_renderer()
        state.current_program = 2  # SOLO stored as 3, base 1 -> wire 2
        self.assertEqual(renderer._slot_status_color(get_slot(state, 1), 1), "#3399FF")

    def test_both_active_flickers_with_2s_period(self):
        renderer, state = make_renderer()
        state.effect_states[(1, 21)] = True
        state.current_program = 2
        slot = get_slot(state, 1)
        with patch("ui.renderer.time.monotonic", return_value=0.4):
            self.assertEqual(renderer._slot_status_color(slot, 1), "#00FF66")
        with patch("ui.renderer.time.monotonic", return_value=1.4):
            self.assertEqual(renderer._slot_status_color(slot, 1), "#3399FF")
        with patch("ui.renderer.time.monotonic", return_value=2.4):
            self.assertEqual(renderer._slot_status_color(slot, 1), "#00FF66")

    def test_action_cc_pressed_uses_on_color(self):
        renderer, state = make_renderer()
        slot = get_slot(state, 3)  # TAP action_cc
        self.assertEqual(renderer._slot_status_color(slot, 3), "#303030")
        state.pressed_buttons.add(3)
        self.assertEqual(renderer._slot_status_color(slot, 3), "#FF6600")

    def test_secondary_action_cc_uses_color_duration_window(self):
        renderer, state = make_renderer()
        slot = get_slot(state, 1)
        slot["secondary"]["action"] = {
            "type": "action_cc", "midi_channel": 1, "cc_number": 50,
            "on_color": "#FF00FF", "label": "STAB", "color_duration": 2.0,
        }
        # The hold fired at t=10 with a 2 s color window (set by ActionLogic).
        state.secondary_color_until[(1, 1)] = 12.0
        with patch("ui.renderer.time.monotonic", return_value=11.0):
            self.assertEqual(renderer._slot_status_color(slot, 1), "#FF00FF")
        # Window expired -> back to the primary off color, even if still held.
        state.pressed_buttons.add(1)
        state.secondary_pressed.add(1)
        with patch("ui.renderer.time.monotonic", return_value=12.5):
            self.assertEqual(renderer._slot_status_color(slot, 1), "#303030")

    def test_expression_active_uses_on_color(self):
        renderer, state = make_renderer()
        slot = get_slot(state, 6)  # VOLUME expression, on #FFCC00
        self.assertEqual(renderer._slot_status_color(slot, 6), "#303030")
        state.expression_mode = (1, 6, "primary")
        self.assertEqual(renderer._slot_status_color(slot, 6), "#FFCC00")

    def test_program_change_active_respects_base(self):
        renderer, state = make_renderer()
        slot = get_slot(state, 4)  # RHYTHM stored as 1, base 1 -> wire 0
        state.current_program = 0
        self.assertEqual(renderer._slot_status_color(slot, 4), "#3399FF")
        state.current_program = 1
        self.assertEqual(renderer._slot_status_color(slot, 4), "#303030")


class ColorMigrationTests(unittest.TestCase):
    def test_old_field_names_are_migrated(self):
        config = default_config()
        slots = config["menus"][0]["slots"]
        # Rewrite some actions in the pre-migration shapes.
        slots["3"]["primary"] = {
            "type": "action_cc", "midi_channel": 1, "cc_number": 23,
            "default_color": "#111111", "pressed_color": "#222222", "label": "TAP",
        }
        slots["4"]["primary"] = {
            "type": "program_change", "midi_channel": 1, "program_number": 1,
            "inactive_color": "#333333", "active_color": "#444444", "label": "R",
        }
        slots["6"]["primary"] = {
            "type": "expression_pedal", "midi_channel": 1, "cc_number": 7,
            "color": "#555555", "label": "VOL", "value_min": 0, "value_max": 127,
            "reverse": False, "has_home": False, "home_value": 0,
        }
        slots["1"]["secondary"]["action"] = {
            "type": "program_change", "midi_channel": 1, "program_number": 3,
            "inactive_color": "#666666", "active_color": "#777777", "label": "SOLO",
        }
        self.assertTrue(_normalize_colors(config))
        self.assertEqual(slots["3"]["primary"]["on_color"], "#222222")
        self.assertEqual(slots["3"]["primary"]["off_color"], "#111111")
        self.assertNotIn("pressed_color", slots["3"]["primary"])
        self.assertEqual(slots["4"]["primary"]["on_color"], "#444444")
        self.assertEqual(slots["4"]["primary"]["off_color"], "#333333")
        self.assertEqual(slots["6"]["primary"]["on_color"], "#555555")
        self.assertEqual(slots["6"]["primary"]["off_color"], "#303030")
        self.assertNotIn("color", slots["6"]["primary"])
        secondary = slots["1"]["secondary"]["action"]
        self.assertEqual(secondary["on_color"], "#777777")
        self.assertNotIn("off_color", secondary)
        self.assertNotIn("inactive_color", secondary)

    def test_current_config_is_untouched(self):
        config = default_config()
        self.assertFalse(_normalize_colors(config))

    def test_nothing_actions_keep_color(self):
        config = default_config()
        self.assertFalse(_normalize_colors(config))
        self.assertEqual(
            config["menus"][0]["slots"]["8"]["primary"]["color"], "#1A1A1A"
        )


if __name__ == "__main__":
    unittest.main()
