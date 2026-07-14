"""ButtonReader debounce + reconcile tests (no GPIO hardware).

The inversion bug these guard against: a genuine release landing inside the
debounce window was dropped without updating the tracked state, so the
reader kept thinking "pressed" — the next physical press was deduped as a
repeat and every event from then on arrived inverted. The reconcile timer
reads the real pin level just after the window and emits the correction.
"""

import unittest
from unittest import mock

from hardware.buttons import ButtonReader


class FakeButton:
    def __init__(self):
        self.is_pressed = False

    def close(self):
        pass


class ButtonReaderTest(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        patcher = mock.patch("hardware.buttons.time")
        self.addCleanup(patcher.stop)
        patcher.start().monotonic = lambda: self.now

        self.events = []
        self.reader = ButtonReader({"buttons": {"debounce_ms": 30}},
                                   self.events.append)
        # Timers are exercised separately; here reconcile runs on demand.
        self.scheduled = []
        self.reader._schedule_reconcile = (
            lambda num: self.scheduled.append(num))
        self.button = FakeButton()
        self.reader._buttons[1] = self.button

    def edge(self, kind, t, pressed=None):
        self.now = t
        if pressed is not None:
            self.button.is_pressed = pressed
        self.reader._edge(1, kind)

    def reconcile(self, t, pressed):
        self.now = t
        self.button.is_pressed = pressed
        self.reader._reconcile(1)

    def kinds(self):
        return [(kind, t) for _num, kind, t in self.events]

    def test_press_and_release_pass_through(self):
        self.edge("press", 0.0, pressed=True)
        self.edge("release", 0.1, pressed=False)
        self.assertEqual(self.kinds(), [("press", 0.0), ("release", 0.1)])

    def test_same_kind_edges_deduplicated(self):
        self.edge("press", 0.0, pressed=True)
        self.edge("press", 0.1)
        self.assertEqual(self.kinds(), [("press", 0.0)])

    def test_initial_release_edge_ignored(self):
        self.edge("release", 0.0, pressed=False)
        self.assertEqual(self.events, [])

    def test_bounce_inside_window_dropped_but_reconciled_when_held(self):
        self.edge("press", 0.0, pressed=True)
        self.edge("release", 0.005)  # contact bounce, still physically held
        self.edge("press", 0.010)
        self.assertEqual(self.kinds(), [("press", 0.0)])
        self.reconcile(0.035, pressed=True)  # settled: still down, no event
        self.assertEqual(self.kinds(), [("press", 0.0)])

    def test_quick_tap_release_inside_window_is_recovered(self):
        # THE inversion bug: the real release lands inside the window.
        self.edge("press", 0.0, pressed=True)
        self.edge("release", 0.02, pressed=False)  # dropped by debounce
        self.assertEqual(self.kinds(), [("press", 0.0)])
        self.reconcile(0.035, pressed=False)
        self.assertEqual(self.kinds(), [("press", 0.0), ("release", 0.035)])
        # ...and the NEXT press must arrive as a press, not be deduped.
        self.edge("press", 0.5, pressed=True)
        self.edge("release", 0.6, pressed=False)
        self.assertEqual(self.kinds()[-2:], [("press", 0.5), ("release", 0.6)])

    def test_reconcile_matching_state_is_silent(self):
        self.edge("press", 0.0, pressed=True)
        self.reconcile(0.035, pressed=True)
        self.assertEqual(self.kinds(), [("press", 0.0)])

    def test_reconcile_inside_window_reschedules(self):
        self.edge("press", 0.0, pressed=True)
        self.scheduled.clear()
        self.reconcile(0.02, pressed=False)  # window still open: no event yet
        self.assertEqual(self.kinds(), [("press", 0.0)])
        self.assertEqual(self.scheduled, [1])
        self.reconcile(0.035, pressed=False)
        self.assertEqual(self.kinds(), [("press", 0.0), ("release", 0.035)])

    def test_every_edge_schedules_a_reconcile(self):
        self.edge("press", 0.0, pressed=True)
        self.edge("release", 0.01)  # dropped, but still checked later
        self.assertEqual(self.scheduled, [1, 1])


class ButtonReaderTimerTest(unittest.TestCase):
    """Real timers end to end (small real-time waits)."""

    def _make(self):
        events = []
        reader = ButtonReader({"buttons": {"debounce_ms": 20}}, events.append)
        button = FakeButton()
        reader._buttons[1] = button
        return reader, button, events

    def test_timer_emits_corrective_release(self):
        import time
        reader, button, events = self._make()
        button.is_pressed = True
        reader._edge(1, "press")
        button.is_pressed = False
        reader._edge(1, "release")  # inside the 20 ms window: dropped
        time.sleep(0.08)  # timer fires at ~25 ms
        self.assertEqual([kind for _n, kind, _t in events],
                         ["press", "release"])
        reader.stop()

    def test_one_pending_timer_per_pin(self):
        reader, button, events = self._make()
        button.is_pressed = True
        reader._edge(1, "press")
        first = reader._timers[1]
        reader._edge(1, "press")  # dedupe path still calls schedule
        self.assertIs(reader._timers[1], first)
        reader.stop()
        self.assertEqual(reader._timers, {})


if __name__ == "__main__":
    unittest.main()
