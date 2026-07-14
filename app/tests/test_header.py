"""Header layout rules (logic/header.py) + the web API validator.

The invariant, in both directions: one item per position, one position per
item. Placing an item somewhere vacates wherever it used to be AND evicts
whatever used to be there — otherwise the header can show the same thing twice,
or an item can quietly live in two places.
"""

import unittest

from logic import header
from web.server import _header_slots


class AssignTest(unittest.TestCase):
    def test_assign_places_the_item(self):
        slots = header.assign([None] * 5, "bpm", 2)
        self.assertEqual(slots, [None, None, "bpm", None, None])

    def test_assign_vacates_the_items_previous_position(self):
        slots = header.assign(["bpm", None, None, None, None], "bpm", 4)
        self.assertEqual(slots, [None, None, None, None, "bpm"])

    def test_assign_evicts_whatever_held_the_position(self):
        slots = header.assign(["patch", None, None, None, None], "bpm", 0)
        self.assertEqual(slots, ["bpm", None, None, None, None])

    def test_assign_handles_a_swap_into_an_occupied_slot(self):
        """The evicted item is dropped, not silently duplicated elsewhere."""
        slots = header.assign(["patch", "bpm", None, None, None], "bpm", 0)
        self.assertEqual(slots, ["bpm", None, None, None, None])

    def test_unknown_item_or_position_is_ignored(self):
        start = ["patch", None, None, None, "bpm"]
        self.assertEqual(header.assign(start, "nonsense", 1), start)
        self.assertEqual(header.assign(start, "midi", 9), start)

    def test_clear_removes_the_item(self):
        slots = header.clear(["patch", None, None, None, "bpm"], "patch")
        self.assertEqual(slots, [None, None, None, None, "bpm"])

    def test_normalize_repairs_a_hand_edited_config(self):
        """Wrong length, junk keys and duplicates must not reach the renderer."""
        self.assertEqual(
            header.normalize(["patch", "patch", "nope", "bpm"]),
            ["patch", None, None, "bpm", None])
        self.assertEqual(header.normalize(None), [None] * 5)
        self.assertEqual(header.normalize("patch"), [None] * 5)

    def test_position_of(self):
        slots = ["patch", None, None, None, "bpm"]
        self.assertEqual(header.position_of(slots, "bpm"), 4)
        self.assertIsNone(header.position_of(slots, "midi"))


class WebValidatorTest(unittest.TestCase):
    """The API must enforce the same rule — the browser is not the only caller."""

    def test_accepts_a_valid_layout(self):
        value = ["patch", None, "midi", None, "bpm"]
        self.assertEqual(_header_slots(value), value)

    def test_rejects_a_duplicate_item(self):
        with self.assertRaises(ValueError):
            _header_slots(["bpm", "bpm", None, None, None])

    def test_rejects_an_unknown_item(self):
        with self.assertRaises(ValueError):
            _header_slots(["bpm", None, None, None, "battery"])

    def test_rejects_the_wrong_length(self):
        with self.assertRaises(ValueError):
            _header_slots(["bpm", None])


if __name__ == "__main__":
    unittest.main()
