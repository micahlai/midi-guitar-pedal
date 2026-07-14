"""Footswitch multi-tap text entry (logic/keypad.py)."""

import unittest

from logic.keypad import KEY_DELETE, KEY_LEFT, KEY_RIGHT, KEY_SHIFT, MultiTapKeypad


class MultiTapKeypadTest(unittest.TestCase):
    def setUp(self):
        self.keypad = MultiTapKeypad()

    def tap(self, button, at=0.0):
        self.keypad.press(button, at)

    def test_single_tap_types_first_character(self):
        self.tap(2)
        self.assertEqual(self.keypad.text, "a")
        self.assertEqual(self.keypad.cursor, 1)

    def test_repeat_tap_cycles_within_the_same_character(self):
        self.tap(2, 0.0)
        self.tap(2, 0.2)
        self.tap(2, 0.4)
        self.assertEqual(self.keypad.text, "c")
        self.assertEqual(self.keypad.cursor, 1)

    def test_cycle_wraps_past_the_last_character(self):
        for i in range(8):  # B2 holds 7 letters
            self.tap(2, i * 0.1)
        self.assertEqual(self.keypad.text, "a")

    def test_timeout_commits_and_starts_a_new_character(self):
        self.tap(2, 0.0)
        self.tap(2, 2.0)  # well past MULTITAP_SECONDS
        self.assertEqual(self.keypad.text, "aa")

    def test_different_key_commits_immediately(self):
        self.tap(2, 0.0)
        self.tap(3, 0.1)
        self.assertEqual(self.keypad.text, "ah")

    def test_shift_latches_and_uppercases(self):
        self.tap(KEY_SHIFT)
        self.tap(2, 0.0)
        self.assertEqual(self.keypad.text, "A")
        self.tap(KEY_SHIFT)  # unlatch
        self.tap(3, 1.5)
        self.assertEqual(self.keypad.text, "Ah")

    def test_shift_does_not_break_digits_or_symbols(self):
        self.tap(KEY_SHIFT)
        self.tap(1, 0.0)
        self.assertEqual(self.keypad.text, "0")

    def test_delete_removes_left_of_cursor(self):
        self.tap(2, 0.0)
        self.tap(3, 1.5)
        self.tap(KEY_DELETE)
        self.assertEqual(self.keypad.text, "a")
        self.assertEqual(self.keypad.cursor, 1)

    def test_delete_on_empty_is_harmless(self):
        self.tap(KEY_DELETE)
        self.assertEqual(self.keypad.text, "")
        self.assertEqual(self.keypad.cursor, 0)

    def test_cursor_moves_and_types_mid_string(self):
        self.tap(2, 0.0)
        self.tap(3, 1.5)  # "ah"
        self.tap(KEY_LEFT)
        self.tap(1, 3.0)  # digit inserted before "h"
        self.assertEqual(self.keypad.text, "a0h")
        self.assertEqual(self.keypad.cursor, 2)

    def test_cursor_clamps_at_both_ends(self):
        self.tap(KEY_LEFT)
        self.assertEqual(self.keypad.cursor, 0)
        self.tap(2, 0.0)
        self.tap(KEY_RIGHT)
        self.tap(KEY_RIGHT)
        self.assertEqual(self.keypad.cursor, 1)

    def test_cursor_move_ends_the_multitap_window(self):
        """Moving away and back must not resume cycling the old character."""
        self.tap(2, 0.0)
        self.tap(KEY_LEFT)
        self.tap(KEY_RIGHT)
        self.tap(2, 0.2)  # within the timeout, but no longer pending
        self.assertEqual(self.keypad.text, "aa")

    def test_max_chars_enforced(self):
        keypad = MultiTapKeypad(max_chars=3)
        for i in range(6):
            keypad.press(2, i * 2.0)  # each past the timeout: a fresh char
        self.assertEqual(keypad.text, "aaa")

    def test_insert_types_a_literal_character(self):
        self.keypad.insert("Z")
        self.keypad.insert("9")
        self.assertEqual(self.keypad.text, "Z9")
        self.assertEqual(self.keypad.cursor, 2)

    def test_reset_clears_everything(self):
        self.tap(2)
        self.tap(KEY_SHIFT)
        self.keypad.reset()
        self.assertEqual(self.keypad.text, "")
        self.assertEqual(self.keypad.cursor, 0)
        self.assertFalse(self.keypad.shift)


if __name__ == "__main__":
    unittest.main()
