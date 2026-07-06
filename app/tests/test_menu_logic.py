"""Unit tests for MenuLogic. Run from app/: python3 -m unittest discover tests"""

import unittest

from config.defaults import default_config
from logic.menu import MenuLogic
from state.manager import StateManager


class MenuLogicTest(unittest.TestCase):
    def setUp(self):
        config = default_config()
        self.state = StateManager(config)
        self.actions = []
        self.logic = MenuLogic(
            config, self.state,
            on_action_event=lambda num, kind: self.actions.append((num, kind)),
        )

    def press(self, num, t):
        self.logic.handle_event((num, "press", t))

    def release(self, num, t):
        self.logic.handle_event((num, "release", t))

    def test_shift_short_press_toggles_menu_1_2(self):
        self.press(10, 0.0)
        self.release(10, 0.2)
        self.assertEqual(self.state.current_menu, 2)
        self.press(10, 1.0)
        self.release(10, 1.2)
        self.assertEqual(self.state.current_menu, 1)

    def test_shift_short_press_from_menu_3_returns_to_menu_1(self):
        self.state.current_menu = 3
        self.press(10, 0.0)
        self.release(10, 0.2)
        self.assertEqual(self.state.current_menu, 1)

    def test_shift_hold_opens_menu_4_and_release_does_not_toggle(self):
        self.press(10, 0.0)
        self.logic.tick(1.0)
        self.assertEqual(self.state.current_menu, 1)
        self.logic.tick(2.0)
        self.assertEqual(self.state.current_menu, 4)
        self.release(10, 2.5)
        self.assertEqual(self.state.current_menu, 4)

    def test_shift_b5_combo_opens_menu_3_suppresses_b5(self):
        self.press(10, 0.0)
        self.press(5, 0.3)
        self.assertEqual(self.state.current_menu, 3)
        self.release(5, 0.5)
        self.release(10, 0.6)
        # No B5 action events, no menu toggle from shift release.
        self.assertEqual(self.actions, [])
        self.assertEqual(self.state.current_menu, 3)

    def test_shift_b5_combo_cancels_menu_4_timer(self):
        self.press(10, 0.0)
        self.press(5, 0.3)
        self.logic.tick(5.0)
        self.assertEqual(self.state.current_menu, 3)

    def test_b5_alone_is_normal_button(self):
        self.press(5, 0.0)
        self.release(5, 0.2)
        self.assertEqual(self.actions, [(5, "press"), (5, "release")])
        self.assertEqual(self.state.current_menu, 1)

    def test_assignable_press_release_events(self):
        self.press(3, 0.0)
        self.release(3, 0.2)
        self.assertEqual(self.actions, [(3, "press"), (3, "release")])

    def test_hold_threshold_fires_once(self):
        self.press(7, 0.0)
        self.logic.tick(1.0)
        self.assertEqual(self.actions, [(7, "press")])
        self.logic.tick(1.6)
        self.logic.tick(2.0)
        self.assertEqual(self.actions, [(7, "press"), (7, "hold")])
        self.release(7, 2.5)
        self.assertEqual(self.actions[-1], (7, "release"))

    def test_shift_state_tracked(self):
        self.press(10, 0.0)
        self.assertTrue(self.state.shift_held)
        self.release(10, 0.2)
        self.assertFalse(self.state.shift_held)


if __name__ == "__main__":
    unittest.main()
