"""Selection groups: action_cc buttons that latch as a radio set (Milestone 18).

The latching is a display concept, but the group does reach the wire in one
respect: the member losing the selection is sent velocity 0, so exactly one
member of the group is on at the rig too.
"""

import unittest

from config.defaults import default_config
from logic import groups
from logic.actions import ActionLogic
from state.manager import StateManager
from tests.test_actions_expression import FakeMidi
from ui.renderer import UiRenderer


def pad_key_menu(config):
    """Menu 1 buttons 1-3 as C/D/E action_cc in the "Pad Key" group, plus an
    ungrouped action_cc on button 4 to prove the old behavior is untouched."""
    config["selection_groups"][0] = "Pad Key"
    slots = config["menus"][0]["slots"]
    for button, (note, label) in enumerate(
            [(60, "C"), (62, "D"), (64, "E")], start=1):
        slots[str(button)] = {"primary": {
            "type": "action_cc", "midi_channel": 1, "cc_number": note,
            "off_color": "#303030", "on_color": "#FF6600",
            "label": label, "selection_group": 1,
        }}
    slots["4"] = {"primary": {
        "type": "action_cc", "midi_channel": 1, "cc_number": 70,
        "off_color": "#303030", "on_color": "#FF6600",
        "label": "TAP", "selection_group": 0,
    }}


class GroupSelectionTest(unittest.TestCase):
    def setUp(self):
        self.config = default_config()
        pad_key_menu(self.config)
        self.state = StateManager(self.config)
        self.midi = FakeMidi()
        self.logic = ActionLogic(self.config, self.state, self.midi)

    def active(self, button):
        """What the renderer would draw: is this button's on_color showing?"""
        action = self.config["menus"][0]["slots"][str(button)]["primary"]
        return UiRenderer._action_active(self, action, button, "primary")

    def press(self, button, t=0.0):
        self.logic.on_button_event(button, "press", t)
        self.logic.on_button_event(button, "release", t + 0.1)

    def test_nothing_selected_before_a_press(self):
        self.assertIsNone(groups.selected_label(self.config, self.state, 1))
        self.assertEqual(groups.header_text(self.config, self.state, 1),
                         "Pad Key - None")
        self.assertFalse(self.active(1))

    def test_press_latches_and_the_next_press_takes_it_over(self):
        self.press(1)  # C
        # Latched: it stays lit after the release, unlike a momentary action_cc.
        self.assertTrue(self.active(1))
        self.assertEqual(groups.header_text(self.config, self.state, 1),
                         "Pad Key - C")

        self.press(2)  # D takes the group
        self.assertFalse(self.active(1))
        self.assertTrue(self.active(2))
        self.assertEqual(groups.header_text(self.config, self.state, 1),
                         "Pad Key - D")

    def test_the_outgoing_member_is_turned_off(self):
        self.press(1)  # C on
        self.assertEqual(self.midi.sent, [("note", 1, 60, 127)])
        self.press(2)  # D takes the group: C off FIRST, then D on
        self.assertEqual(self.midi.sent, [
            ("note", 1, 60, 127),
            ("note", 1, 60, 0),    # C released
            ("note", 1, 62, 127),  # D pressed
        ])

    def test_pressing_the_selected_member_again_does_not_blip_it_off(self):
        self.press(1)
        self.press(1)
        # A 0 followed by a 127 on the same note would briefly kill the effect
        # that is staying on.
        self.assertEqual(self.midi.sent,
                         [("note", 1, 60, 127), ("note", 1, 60, 127)])

    def test_first_selection_turns_nothing_off(self):
        self.press(3)  # nothing held the group yet
        self.assertEqual(self.midi.sent, [("note", 1, 64, 127)])

    def test_ungrouped_action_cc_wire_traffic_is_unchanged(self):
        self.press(4)  # TAP, ungrouped
        self.press(4)
        self.assertEqual(self.midi.sent,
                         [("note", 1, 70, 127), ("note", 1, 70, 127)])

    def test_ungrouped_action_cc_stays_momentary(self):
        self.logic.on_button_event(4, "press", 0.0)
        self.assertTrue(self.active(4))  # lit only while held
        self.logic.on_button_event(4, "release", 0.1)
        self.assertFalse(self.active(4))

    def test_selection_is_dropped_when_the_button_leaves_the_group(self):
        self.press(1)
        self.assertTrue(self.active(1))
        # Re-assigned out of the group from the web app under a live selection:
        # the header must not keep naming it, and it must not stay lit.
        self.config["menus"][0]["slots"]["1"]["primary"]["selection_group"] = 0
        self.assertFalse(self.active(1))
        self.assertEqual(groups.header_text(self.config, self.state, 1),
                         "Pad Key - None")

    def test_groups_are_independent(self):
        self.config["selection_groups"][1] = "Amp"
        self.config["menus"][0]["slots"]["5"] = {"primary": {
            "type": "action_cc", "midi_channel": 1, "cc_number": 80,
            "off_color": "#303030", "on_color": "#00FF66",
            "label": "CLEAN", "selection_group": 2,
        }}
        self.press(1)  # Pad Key: C
        self.press(5)  # Amp: CLEAN — a different group, so C stays lit
        self.assertTrue(self.active(1))
        self.assertTrue(self.active(5))
        self.assertEqual(groups.header_text(self.config, self.state, 1), "Pad Key - C")
        self.assertEqual(groups.header_text(self.config, self.state, 2), "Amp - CLEAN")


class GroupHelpersTest(unittest.TestCase):
    def setUp(self):
        self.config = default_config()

    def test_unnamed_group_still_reads_as_something(self):
        self.assertEqual(groups.group_name(self.config, 3), "Group 3")

    def test_names_survive_a_hand_edited_config(self):
        self.config["selection_groups"] = ["Pad Key", 7, None]  # short and junky
        self.assertEqual(groups.group_names(self.config),
                         ["Pad Key", "", "", "", ""])

    def test_only_action_cc_can_join_a_group(self):
        self.assertIsNone(groups.action_group(
            {"type": "effect_cc", "selection_group": 1}))
        self.assertIsNone(groups.action_group(
            {"type": "action_cc", "selection_group": 9}))  # out of range
        self.assertEqual(groups.action_group(
            {"type": "action_cc", "selection_group": 2}), 2)

    def test_header_items_end_with_the_five_groups(self):
        from logic import header
        self.assertEqual([key for key, _ in header.HEADER_ITEMS][-5:],
                         ["group1", "group2", "group3", "group4", "group5"])
        self.assertEqual(header.HEADER_ITEMS[-5][1], "Selection Group 1")


if __name__ == "__main__":
    unittest.main()
