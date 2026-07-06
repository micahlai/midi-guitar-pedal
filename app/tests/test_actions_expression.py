"""Unit tests for ActionLogic and ExpressionLogic (fake MIDI engine)."""

import unittest

from config.defaults import default_config
from logic.actions import ActionLogic
from logic.expression import ExpressionLogic, map_value
from state.manager import StateManager


class FakeMidi:
    def __init__(self):
        self.sent = []

    def send_cc(self, channel, cc, value):
        self.sent.append(("cc", channel, cc, value))

    def send_note(self, channel, note, velocity=127):
        self.sent.append(("note", channel, note, velocity))

    def send_program_change(self, channel, program):
        self.sent.append(("pc", channel, program))


class ActionLogicTest(unittest.TestCase):
    def setUp(self):
        self.config = default_config()
        self.state = StateManager(self.config)
        self.midi = FakeMidi()
        self.expression = ExpressionLogic(self.config, self.state, self.midi)
        self.logic = ActionLogic(self.config, self.state, self.midi, self.expression)

    def test_action_cc_sends_and_tracks_pressed(self):
        self.logic.on_button_event(3, "press", 0.0)  # TAP, cc 23
        self.assertEqual(self.midi.sent, [("note", 1, 23, 127)])
        self.assertIn(3, self.state.pressed_buttons)
        self.logic.on_button_event(3, "release", 0.2)
        self.assertNotIn(3, self.state.pressed_buttons)
        self.assertEqual(len(self.midi.sent), 1)  # release sends nothing

    def test_program_change_sends_pc(self):
        self.logic.on_button_event(5, "press", 0.0)  # LEAD, program 2
        self.assertEqual(self.midi.sent, [("pc", 1, 2)])

    def test_expression_button_sets_mode_no_midi(self):
        self.logic.on_button_event(6, "press", 0.0)  # VOLUME
        self.assertEqual(self.state.expression_mode, (1, 6, "primary"))
        self.assertEqual(self.midi.sent, [])

    def test_nothing_and_unassigned_send_nothing(self):
        self.logic.on_button_event(8, "press", 0.0)  # nothing
        self.state.current_menu = 2
        self.logic.on_button_event(1, "press", 0.0)  # menu 2 empty
        self.assertEqual(self.midi.sent, [])

    # --- Milestone 10: secondary hold semantics (B1 = DRIVE + SOLO secondary)

    def test_primary_with_secondary_waits_and_fires_on_quick_release(self):
        self.logic.on_button_event(1, "press", 0.0)
        self.assertEqual(self.midi.sent, [])  # waits for release
        self.logic.tick(0.5)
        self.assertEqual(self.midi.sent, [])
        self.logic.on_button_event(1, "release", 1.0)  # before 1.5s threshold
        self.assertEqual(self.midi.sent, [("note", 1, 21, 127)])  # primary DRIVE

    def test_secondary_fires_on_hold_and_release_is_inert(self):
        self.logic.on_button_event(1, "press", 0.0)
        self.logic.tick(1.5)
        self.assertEqual(self.midi.sent, [("pc", 1, 3)])  # secondary SOLO
        self.logic.tick(2.0)  # does not refire
        self.logic.on_button_event(1, "release", 2.5)  # no primary
        self.assertEqual(self.midi.sent, [("pc", 1, 3)])

    def test_primary_without_secondary_fires_immediately(self):
        self.logic.on_button_event(2, "press", 0.0)  # DELAY, no secondary
        self.assertEqual(self.midi.sent, [("note", 1, 22, 127)])

    def test_per_slot_hold_threshold(self):
        slot = self.config["menus"][0]["slots"]["1"]
        slot["secondary"]["hold_seconds"] = 3.0
        self.logic.on_button_event(1, "press", 0.0)
        self.logic.tick(2.0)  # past default 1.5 but below slot's 3.0
        self.assertEqual(self.midi.sent, [])
        self.logic.tick(3.0)
        self.assertEqual(self.midi.sent, [("pc", 1, 3)])


class MapValueTest(unittest.TestCase):
    def test_full_range(self):
        action = {"value_min": 0, "value_max": 127, "reverse": False}
        self.assertEqual(map_value(action, 0.0), 0)
        self.assertEqual(map_value(action, 1.0), 127)
        self.assertEqual(map_value(action, 0.5), 64)

    def test_reverse(self):
        action = {"value_min": 0, "value_max": 127, "reverse": True}
        self.assertEqual(map_value(action, 0.0), 127)
        self.assertEqual(map_value(action, 1.0), 0)

    def test_sub_range_and_clamp(self):
        action = {"value_min": 20, "value_max": 100, "reverse": False}
        self.assertEqual(map_value(action, 0.0), 20)
        self.assertEqual(map_value(action, 1.0), 100)
        action = {"value_min": -10, "value_max": 200, "reverse": False}
        self.assertEqual(map_value(action, 0.0), 0)
        self.assertEqual(map_value(action, 1.0), 127)


class ExpressionLogicTest(unittest.TestCase):
    def setUp(self):
        self.config = default_config()
        self.state = StateManager(self.config)
        self.state.expression_detected = True
        self.midi = FakeMidi()
        self.logic = ExpressionLogic(self.config, self.state, self.midi)

    def test_pot_sends_cc_with_deadband(self):
        self.state.expression_mode = (1, 6, "primary")  # VOLUME cc 7
        self.state.expression_value = 0.5
        self.logic.tick(0.0)
        self.assertEqual(self.midi.sent, [("cc", 1, 7, 64)])
        self.logic.tick(0.01)  # unchanged -> no resend
        self.assertEqual(len(self.midi.sent), 1)
        self.state.expression_value = 1.0
        self.logic.tick(0.02)
        self.assertEqual(self.midi.sent[-1], ("cc", 1, 7, 127))

    def test_no_send_without_mode_or_detection(self):
        self.state.expression_value = 0.7
        self.logic.tick(0.0)
        self.state.expression_mode = (1, 6, "primary")
        self.state.expression_detected = False
        self.logic.tick(0.1)
        self.assertEqual(self.midi.sent, [])

    def test_home_return_walks_cc_back(self):
        # Activate WAH (has_home, home 0), move pot, then switch to VOLUME.
        self.state.expression_mode = (1, 7, "primary")  # WAH cc 11
        self.state.expression_value = 1.0
        self.logic.tick(0.0)
        self.assertEqual(self.midi.sent[-1], ("cc", 1, 11, 127))
        self.logic.set_mode((1, 6, "primary"))
        # Pot still at 1.0 -> VOLUME sends immediately; WAH returns over ticks.
        t = 0.0
        for _ in range(200):
            t += 0.03
            self.logic.tick(t)
        wah_values = [v for (k, ch, cc, v) in self.midi.sent if k == "cc" and cc == 11]
        self.assertEqual(wah_values[-1], 0)  # reached home
        self.assertTrue(all(a >= b for a, b in zip(wah_values, wah_values[1:])),
                        f"not monotonically decreasing: {wah_values}")
        self.assertNotIn((1, 11), self.logic._returns)


if __name__ == "__main__":
    unittest.main()
