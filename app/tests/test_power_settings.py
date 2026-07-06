"""Unit tests for PowerLogic and SettingsLogic."""

import unittest

from config.defaults import default_config
from logic.power import PowerLogic
from logic.settings import SETTINGS_ITEMS, SettingsLogic
from state.manager import StateManager


class PowerLogicTest(unittest.TestCase):
    def setUp(self):
        config = default_config()
        self.state = StateManager(config)
        self.logic = PowerLogic(config, self.state)

    def tap(self, t):
        self.logic.handle_event((0, "press", t))
        self.logic.handle_event((0, "release", t + 0.05))

    def test_single_press_does_nothing(self):
        self.tap(0.0)
        self.assertFalse(self.state.settings_open)

    def test_double_press_opens_settings(self):
        self.tap(0.0)
        self.tap(0.3)
        self.assertTrue(self.state.settings_open)

    def test_slow_presses_do_not_open(self):
        self.tap(0.0)
        self.tap(1.0)
        self.assertFalse(self.state.settings_open)
        # But the second press starts a new window.
        self.tap(1.3)
        self.assertTrue(self.state.settings_open)

    def test_double_press_again_closes(self):
        self.tap(0.0)
        self.tap(0.3)
        self.tap(2.0)
        self.tap(2.3)
        self.assertFalse(self.state.settings_open)

    def test_triple_press_does_not_retoggle(self):
        self.tap(0.0)
        self.tap(0.2)
        self.tap(0.4)  # third press starts a fresh window, no toggle
        self.assertTrue(self.state.settings_open)

    def test_hold_fires_shutdown_stub_once(self):
        self.logic.handle_event((0, "press", 0.0))
        self.logic.tick(1.0)
        self.assertFalse(self.logic._hold_fired)
        self.logic.tick(3.0)
        self.assertTrue(self.logic._hold_fired)


class SettingsLogicTest(unittest.TestCase):
    def setUp(self):
        config = default_config()
        self.state = StateManager(config)
        self.state.settings_open = True
        self.logic = SettingsLogic(self.state)

    def press(self, num):
        self.logic.handle_event((num, "press", 0.0))

    def test_down_up_navigation_wraps(self):
        self.press(7)
        self.assertEqual(self.state.settings_index, 1)
        self.press(6)
        self.press(6)
        self.assertEqual(self.state.settings_index, len(SETTINGS_ITEMS) - 1)

    def test_exit_button_closes(self):
        self.press(10)
        self.assertFalse(self.state.settings_open)
        self.assertEqual(self.state.settings_index, 0)

    def test_select_exit_item_closes(self):
        self.state.settings_index = SETTINGS_ITEMS.index("Exit")
        self.press(9)
        self.assertFalse(self.state.settings_open)

    def test_select_stub_item_stays_open(self):
        self.press(9)
        self.assertTrue(self.state.settings_open)

    def test_release_events_ignored(self):
        self.logic.handle_event((7, "release", 0.0))
        self.assertEqual(self.state.settings_index, 0)


if __name__ == "__main__":
    unittest.main()
