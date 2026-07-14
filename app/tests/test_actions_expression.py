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
        # LEAD is stored as program 2 in the rig's 1-based numbering
        # (program_display_base 1) -> wire value 1.
        self.logic.on_button_event(5, "press", 0.0)
        self.assertEqual(self.midi.sent, [("pc", 1, 1)])

    def test_program_change_base_zero_sends_raw(self):
        self.config["midi"]["program_display_base"] = 0
        self.logic.on_button_event(5, "press", 0.0)  # LEAD, program 2
        self.assertEqual(self.midi.sent, [("pc", 1, 2)])

    def test_secondary_hold_tracks_secondary_pressed(self):
        self.logic.on_button_event(1, "press", 0.0)  # DRIVE, secondary SOLO
        self.logic.tick(2.0)  # past the 1.5 s hold -> secondary fires
        self.assertIn(1, self.state.secondary_pressed)
        self.logic.on_button_event(1, "release", 2.1)
        self.assertNotIn(1, self.state.secondary_pressed)

    def test_action_cc_secondary_opens_color_window(self):
        slot = self.config["menus"][0]["slots"]["1"]
        slot["secondary"]["action"] = {
            "type": "action_cc", "midi_channel": 1, "cc_number": 50,
            "on_color": "#FF00FF", "label": "STAB", "color_duration": 2.5,
        }
        self.logic.on_button_event(1, "press", 0.0)
        self.logic.tick(1.5)  # hold threshold -> secondary fires
        self.assertEqual(self.state.secondary_color_until[(1, 1)], 1.5 + 2.5)
        self.logic.on_button_event(1, "release", 1.6)
        # Release does NOT close the window; expiry (pruned in tick) does.
        self.assertIn((1, 1), self.state.secondary_color_until)
        self.logic.tick(4.1)
        self.assertNotIn((1, 1), self.state.secondary_color_until)

    def test_non_action_cc_secondary_opens_no_color_window(self):
        self.logic.on_button_event(1, "press", 0.0)  # secondary SOLO (PC)
        self.logic.tick(2.0)
        self.assertEqual(self.state.secondary_color_until, {})

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
        self.assertEqual(self.midi.sent, [("pc", 1, 2)])  # SOLO: stored 3, base 1
        self.logic.tick(2.0)  # does not refire
        self.logic.on_button_event(1, "release", 2.5)  # no primary
        self.assertEqual(self.midi.sent, [("pc", 1, 2)])  # SOLO: stored 3, base 1

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
        self.assertEqual(self.midi.sent, [("pc", 1, 2)])  # SOLO: stored 3, base 1


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

    def test_retained_value_keeps_sending_while_unplugged(self):
        self.config["expression"]["retain_pedal_value"] = True
        self.state.expression_mode = (1, 6, "primary")  # VOLUME cc 7
        self.state.expression_detected = False
        self.state.expression_value = 0.5  # ADC froze it here at unplug
        self.logic.tick(0.0)
        self.assertEqual(self.midi.sent, [("cc", 1, 7, 64)])


class SelectModeTest(unittest.TestCase):
    """Milestone 17: what a newly selected expression effect does when the pot
    is not where that effect's CC was left. WAH (button 7, cc 11, home 0) and
    VOLUME (button 6, cc 7) are the default config's expression assignments."""

    def setUp(self):
        self.config = default_config()
        self.state = StateManager(self.config)
        self.state.expression_detected = True
        self.midi = FakeMidi()
        self.logic = ExpressionLogic(self.config, self.state, self.midi)

    def set_select_mode(self, mode):
        """select_mode is per-effect now, so set it on both of the default
        config's expression assignments (VOLUME on 6, WAH on 7)."""
        for button in ("6", "7"):
            self.config["menus"][0]["slots"][button]["primary"]["select_mode"] = mode

    def wah_sends(self):
        return [v for (k, ch, cc, v) in self.midi.sent if k == "cc" and cc == 11]

    def leave_wah_returning_home(self):
        """WAH at 127, then switch away — it starts walking home. Stop partway,
        so re-selecting it has to meet a value that is neither 127 nor home."""
        self.state.expression_mode = (1, 7, "primary")  # WAH cc 11
        self.state.expression_value = 1.0
        self.logic.tick(0.0)
        self.assertEqual(self.midi.sent[-1], ("cc", 1, 11, 127))
        self.logic.set_mode((1, 6, "primary"))  # -> VOLUME, WAH returns home
        t = 0.0
        for _ in range(5):
            t += 0.03
            self.logic.tick(t)
        frozen = self.logic._returns[(1, 11)]["current"]
        self.assertTrue(0 < frozen < 127, frozen)
        self.midi.sent.clear()
        return t, frozen

    def test_catch_holds_effect_until_pot_sweeps_onto_it(self):
        self.set_select_mode("catch")
        t, frozen = self.leave_wah_returning_home()
        self.logic.set_mode((1, 7, "primary"))  # back to WAH
        # The home-return stops where it was; that frozen value is the target.
        self.assertNotIn((1, 11), self.logic._returns)
        self.assertEqual(self.logic._pending["target"], round(frozen))

        # Pot is still at the top: WAH must not jump back up to it.
        for _ in range(5):
            t += 0.03
            self.logic.tick(t)
        self.assertEqual(self.wah_sends(), [])

        # Sweep the pot down past the frozen value -> WAH catches and tracks.
        for value in (0.9, 0.7, 0.5, 0.3):
            self.state.expression_value = value
            t += 0.03
            self.logic.tick(t)
        sent = self.wah_sends()
        self.assertTrue(sent, "WAH never caught the pot")
        self.assertLessEqual(sent[0], round(frozen))  # no upward jump
        self.assertEqual(sent[-1], 38)  # pot 0.3 -> tracking exactly

    def test_interpolate_glides_effect_to_the_pot(self):
        self.set_select_mode("interpolate")
        t, frozen = self.leave_wah_returning_home()
        self.state.expression_value = 0.0  # pot parked at the bottom -> WAH 0
        self.logic.set_mode((1, 7, "primary"))
        for _ in range(200):
            t += 0.03
            self.logic.tick(t)
        sent = self.wah_sends()
        self.assertTrue(sent)
        self.assertLess(sent[0], frozen)  # started from where it was left
        self.assertEqual(sent[-1], 0)  # arrived at the pot
        self.assertTrue(all(a >= b for a, b in zip(sent, sent[1:])),
                        f"not monotonic: {sent}")
        self.assertIsNone(self.logic._pending)  # now tracking the pot

    def test_snap_jumps_straight_to_the_pot(self):
        self.set_select_mode("snap")
        t, _frozen = self.leave_wah_returning_home()
        self.state.expression_value = 0.0
        self.logic.set_mode((1, 7, "primary"))
        self.logic.tick(t + 0.03)
        self.assertEqual(self.wah_sends()[0], 0)  # one send, straight to the pot

    def test_sent_value_published_for_the_ui_bar(self):
        # The device bar draws expression_sent_value, and marks the pot in red
        # while the two disagree — so the sent value must stay at the held
        # value, not the pot's, until the effect catches up.
        self.set_select_mode("catch")
        t, frozen = self.leave_wah_returning_home()
        self.logic.set_mode((1, 7, "primary"))
        self.assertEqual(self.state.expression_sent_value, round(frozen))
        for _ in range(5):  # pot still at the top, WAH held
            t += 0.03
            self.logic.tick(t)
        self.assertEqual(self.state.expression_sent_value, round(frozen))
        self.state.expression_value = 0.0  # sweep past it -> caught, tracking
        self.logic.tick(t + 0.03)
        self.assertEqual(self.state.expression_sent_value, 0)

    def test_red_pedal_marker_shows_only_until_the_effect_meets_the_pedal(self):
        self.set_select_mode("catch")
        t, _frozen = self.leave_wah_returning_home()
        self.assertFalse(self.state.expression_meeting_pedal)
        self.logic.set_mode((1, 7, "primary"))  # back to WAH, pot at the top
        self.assertTrue(self.state.expression_meeting_pedal)

        self.state.expression_value = 0.0  # sweep past the held value -> caught
        t += 0.03
        self.logic.tick(t)
        self.assertFalse(self.state.expression_meeting_pedal)
        # Sweeping around afterwards must not bring the marker back: the effect
        # tracks the pedal now, and only a new selection can part them again.
        for value in (0.4, 0.8, 0.2):
            self.state.expression_value = value
            t += 0.03
            self.logic.tick(t)
            self.assertFalse(self.state.expression_meeting_pedal)

    def test_snap_never_shows_the_red_pedal_marker(self):
        self.set_select_mode("snap")
        t, _frozen = self.leave_wah_returning_home()
        self.logic.set_mode((1, 7, "primary"))
        self.assertFalse(self.state.expression_meeting_pedal)
        self.logic.tick(t + 0.03)
        self.assertFalse(self.state.expression_meeting_pedal)

    def test_each_effect_carries_its_own_select_mode_and_speeds(self):
        volume = self.config["menus"][0]["slots"]["6"]["primary"]
        wah = self.config["menus"][0]["slots"]["7"]["primary"]
        volume["select_mode"] = "snap"
        wah["select_mode"] = "catch"
        wah["return_alpha"] = 0.5  # WAH walks home faster than the default

        t, frozen = self.leave_wah_returning_home()
        # WAH's own return_alpha drove that return, not a device-wide one.
        self.assertEqual(self.logic._returns[(1, 11)]["alpha"], 0.5)

        self.logic.set_mode((1, 7, "primary"))  # WAH: catch
        self.assertTrue(self.state.expression_meeting_pedal)
        self.logic.set_mode((1, 6, "primary"))  # VOLUME: snap
        self.assertFalse(self.state.expression_meeting_pedal)

    def test_selecting_an_untouched_effect_always_snaps(self):
        # Nothing has been sent on VOLUME's CC, so there is no value to meet.
        self.set_select_mode("catch")
        self.state.expression_value = 1.0
        self.logic.set_mode((1, 6, "primary"))  # VOLUME cc 7
        self.logic.tick(0.0)
        self.assertEqual(self.midi.sent, [("cc", 1, 7, 127)])


if __name__ == "__main__":
    unittest.main()
