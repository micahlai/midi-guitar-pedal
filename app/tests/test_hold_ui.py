"""Milestone 13.5: hold progress bar state + rescaled growth timing."""

import unittest

from config.defaults import default_config
from logic.actions import ActionLogic
from logic.menu import MenuLogic
from state.manager import StateManager
from ui.renderer import HOLD_GROW_DELAY_S, hold_progress


class HoldProgressMathTest(unittest.TestCase):
    def test_zero_during_initial_delay(self):
        self.assertEqual(hold_progress(10.0, 1.5, 10.0), 0.0)
        self.assertEqual(hold_progress(10.0, 1.5, 10.0 + HOLD_GROW_DELAY_S), 0.0)

    def test_reaches_top_exactly_at_hold_time(self):
        self.assertEqual(hold_progress(10.0, 1.5, 11.5), 1.0)
        # Rescaled: halfway through the growth window (0.2 -> 1.5 s) is 50%.
        mid = 10.0 + HOLD_GROW_DELAY_S + (1.5 - HOLD_GROW_DELAY_S) / 2
        self.assertAlmostEqual(hold_progress(10.0, 1.5, mid), 0.5)

    def test_clamped(self):
        self.assertEqual(hold_progress(10.0, 1.5, 99.0), 1.0)
        self.assertEqual(hold_progress(10.0, 1.5, 9.0), 0.0)

    def test_hold_shorter_than_delay(self):
        self.assertEqual(hold_progress(10.0, 0.125, 10.05), 0.0)
        self.assertEqual(hold_progress(10.0, 0.125, 10.125), 1.0)


class FakeMidi:
    def send_note(self, *a): pass
    def send_program_change(self, *a): pass
    def send_cc(self, *a): pass


class HoldStateTrackingTest(unittest.TestCase):
    def setUp(self):
        self.config = default_config()
        self.state = StateManager(self.config)
        self.actions = ActionLogic(self.config, self.state, FakeMidi())
        self.menu = MenuLogic(self.config, self.state,
                              on_action_event=self.actions.on_button_event)

    def test_button_with_secondary_tracks_hold(self):
        # B1 in defaults has a secondary with hold_seconds 1.5.
        self.menu.handle_event((1, "press", 100.0))
        self.assertEqual(self.state.hold_started[1], (100.0, 1.5))
        # Fires at the threshold -> tracking cleared even though still held.
        self.actions.tick(101.5)
        self.assertNotIn(1, self.state.hold_started)
        self.menu.handle_event((1, "release", 102.0))

    def test_release_before_threshold_clears(self):
        self.menu.handle_event((1, "press", 100.0))
        self.menu.handle_event((1, "release", 100.5))
        self.assertNotIn(1, self.state.hold_started)

    def test_button_without_secondary_not_tracked(self):
        self.menu.handle_event((2, "press", 100.0))  # B2 DELAY, no secondary
        self.assertNotIn(2, self.state.hold_started)
        self.menu.handle_event((2, "release", 100.1))

    def test_shift_tracks_and_clears_on_menu4(self):
        self.menu.handle_event((10, "press", 50.0))
        self.assertEqual(self.state.hold_started[10], (50.0, 2.0))
        self.menu.tick(52.0)  # Menu 4 fires
        self.assertEqual(self.state.current_menu, 4)
        self.assertNotIn(10, self.state.hold_started)

    def test_shift_clears_on_release(self):
        self.menu.handle_event((10, "press", 50.0))
        self.menu.handle_event((10, "release", 50.5))
        self.assertNotIn(10, self.state.hold_started)

    def test_shift_b5_combo_clears(self):
        self.menu.handle_event((10, "press", 50.0))
        self.menu.handle_event((5, "press", 50.3))
        self.assertEqual(self.state.current_menu, 3)
        self.assertNotIn(10, self.state.hold_started)


if __name__ == "__main__":
    unittest.main()
