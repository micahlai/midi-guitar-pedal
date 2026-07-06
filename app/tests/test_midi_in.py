"""Unit tests for MidiInLogic (Milestone 8)."""

import unittest
from types import SimpleNamespace

from config.defaults import default_config
from logic.midi_in import MidiInLogic
from state.manager import StateManager


def cc(channel_1based, control, value):
    return SimpleNamespace(type="control_change", channel=channel_1based - 1,
                           control=control, value=value)


def note_on(channel_1based, note, velocity):
    return SimpleNamespace(type="note_on", channel=channel_1based - 1,
                           note=note, velocity=velocity)


def note_off(channel_1based, note):
    return SimpleNamespace(type="note_off", channel=channel_1based - 1, note=note)


def pc(channel_1based, program):
    return SimpleNamespace(type="program_change", channel=channel_1based - 1,
                           program=program)


class MidiInTest(unittest.TestCase):
    def setUp(self):
        self.config = default_config()
        self.state = StateManager(self.config)
        self.logic = MidiInLogic(self.config, self.state)

    def test_cc_feedback_updates_effect_state(self):
        self.logic.handle_message(cc(1, 21, 127))  # DRIVE on
        self.assertTrue(self.state.effect_states[(1, 21)])
        self.logic.handle_message(cc(1, 21, 0))  # off
        self.assertFalse(self.state.effect_states[(1, 21)])

    def test_any_nonzero_value_is_on(self):
        self.logic.handle_message(cc(1, 22, 1))
        self.assertTrue(self.state.effect_states[(1, 22)])

    def test_unassigned_cc_ignored(self):
        self.logic.handle_message(cc(1, 99, 127))
        self.assertNotIn((1, 99), self.state.effect_states)

    def test_wrong_channel_ignored(self):
        self.logic.handle_message(cc(2, 21, 127))
        self.assertNotIn((2, 21), self.state.effect_states)
        self.assertNotIn((1, 21), self.state.effect_states)

    def test_program_change_sets_global_program(self):
        self.logic.handle_message(pc(1, 5))
        self.assertEqual(self.state.current_program, 5)

    def test_secondary_effect_cc_also_tracked(self):
        # Give B2 a secondary effect_cc and check feedback reaches it.
        self.config["menus"][0]["slots"]["2"]["secondary"] = {
            "enabled": True, "hold_seconds": 1.5,
            "action": {"type": "effect_cc", "midi_channel": 1, "cc_number": 50,
                       "off_color": "#000000", "on_color": "#FFFFFF", "label": "X"},
        }
        self.logic.handle_message(cc(1, 50, 127))
        self.assertTrue(self.state.effect_states[(1, 50)])


class NoteFeedbackTest(MidiInTest):
    def test_note_feedback_updates_effect_state(self):
        self.logic.handle_message(note_on(1, 21, 127))  # DRIVE on
        self.assertTrue(self.state.effect_states[(1, 21)])
        self.logic.handle_message(note_off(1, 21))
        self.assertFalse(self.state.effect_states[(1, 21)])

    def test_note_on_velocity_zero_is_off(self):
        self.logic.handle_message(note_on(1, 21, 127))
        self.logic.handle_message(note_on(1, 21, 0))
        self.assertFalse(self.state.effect_states[(1, 21)])

    def test_unassigned_note_ignored(self):
        self.logic.handle_message(note_on(1, 99, 127))
        self.assertNotIn((1, 99), self.state.effect_states)


if __name__ == "__main__":
    unittest.main()
