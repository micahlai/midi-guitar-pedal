"""Milestone 16 tests: tempo tracking, frame dirty-signature, header text,
power-hold shutdown callback."""

import unittest

from config.defaults import default_config
from logic.power import PowerLogic
from midi.tempo import PULSES_PER_BEAT, TempoTracker
from state.manager import StateManager
from ui.renderer import UiRenderer


def feed_clocks(tracker, bpm, start=0.0, beats=3):
    interval = 60.0 / bpm / PULSES_PER_BEAT
    result = None
    for i in range(int(beats * PULSES_PER_BEAT) + 1):
        result = tracker.clock(start + i * interval)
    return result


class TempoTrackerTest(unittest.TestCase):
    def test_steady_120_bpm(self):
        bpm = feed_clocks(TempoTracker(), 120)
        self.assertAlmostEqual(bpm, 120.0, places=1)

    def test_needs_a_full_beat(self):
        tracker = TempoTracker()
        interval = 60.0 / 100 / PULSES_PER_BEAT
        for i in range(PULSES_PER_BEAT):  # one pulse short
            self.assertIsNone(tracker.clock(i * interval))

    def test_gap_resets_measurement(self):
        tracker = TempoTracker()
        feed_clocks(tracker, 120)
        # After a >1 s gap the old pulses must not pollute the new tempo.
        self.assertIsNone(tracker.clock(100.0))
        bpm = feed_clocks(tracker, 90, start=100.0)
        self.assertAlmostEqual(bpm, 90.0, places=1)

    def test_tracks_tempo_change(self):
        tracker = TempoTracker()
        feed_clocks(tracker, 120)
        bpm = feed_clocks(tracker, 60, start=1.6, beats=4)
        self.assertAlmostEqual(bpm, 60.0, places=1)


class FrameSignatureTest(unittest.TestCase):
    def setUp(self):
        self.state = StateManager(default_config())
        self.state.booting = False
        self.renderer = UiRenderer(self.state)

    def test_stable_when_idle(self):
        self.assertEqual(self.renderer._frame_signature(0.1),
                         self.renderer._frame_signature(0.2))

    def test_changes_on_state_change(self):
        before = self.renderer._frame_signature(0.1)
        self.state.current_menu = 2
        self.assertNotEqual(before, self.renderer._frame_signature(0.1))

    def test_changes_on_config_mutation(self):
        before = self.renderer._frame_signature(0.1)
        self.state.config_version += 1
        self.assertNotEqual(before, self.renderer._frame_signature(0.1))

    def test_none_while_hold_animates(self):
        self.state.hold_started[1] = (0.0, 1.5)
        self.assertIsNone(self.renderer._frame_signature(0.1))

    def test_changes_when_tempo_goes_stale(self):
        self.state.tempo_bpm = 120.0
        self.state.tempo_updated_at = 0.0
        fresh = self.renderer._frame_signature(1.0)
        stale = self.renderer._frame_signature(3.5)
        self.assertNotEqual(fresh, stale)


class BootScreenTest(unittest.TestCase):
    def setUp(self):
        self.state = StateManager(default_config())
        self.renderer = UiRenderer(self.state)

    def test_boot_active_while_booting_and_min_time(self):
        self.assertTrue(self.renderer._boot_active(0.0))  # state.booting
        self.state.boot_log("ready")
        self.state.booting = False
        self.assertFalse(self.renderer._boot_active(100.0))  # display not up
        self.renderer._display_up_at = 100.0
        self.assertTrue(self.renderer._boot_active(101.0))  # min hold time
        self.assertFalse(self.renderer._boot_active(103.0))

    def test_boot_signature_tracks_messages_then_leaves(self):
        first = self.renderer._frame_signature(0.0)
        self.assertEqual(first, ("boot", ()))
        self.state.boot_log("MIDI engine started")
        self.assertNotEqual(first, self.renderer._frame_signature(0.0))
        self.state.booting = False
        # Out of boot: the signature switches to the normal frame tuple.
        self.assertNotEqual(self.renderer._frame_signature(0.0)[0], "boot")

    def test_boot_log_is_atomic_swap(self):
        before = self.state.boot_messages
        self.state.boot_log("one")
        self.assertEqual(before, [])  # old list untouched (render thread safe)
        self.assertEqual(self.state.boot_messages, ["one"])


class HeaderTextTest(unittest.TestCase):
    def setUp(self):
        self.state = StateManager(default_config())
        self.renderer = UiRenderer(self.state)

    def test_tempo_text(self):
        self.assertEqual(self.renderer._tempo_text(0.0), "--- BPM")
        self.state.tempo_bpm = 120.4
        self.state.tempo_updated_at = 10.0
        self.assertEqual(self.renderer._tempo_text(10.5), "120 BPM")
        self.assertEqual(self.renderer._tempo_text(20.0), "--- BPM")

    def test_program_label_base_aware(self):
        # Default config: B4 primary is program_change 1 (display base 1),
        # i.e. wire program 0; B1 secondary "SOLO" is program 3 -> wire 2.
        self.assertEqual(self.renderer._program_label(0), "RHYTHM")
        self.assertEqual(self.renderer._program_label(2), "SOLO")
        self.assertIsNone(self.renderer._program_label(90))


class PowerShutdownTest(unittest.TestCase):
    def test_hold_fires_injected_shutdown_once(self):
        config = default_config()
        state = StateManager(config)
        calls = []
        logic = PowerLogic(config, state, on_shutdown=lambda: calls.append(1))
        logic.handle_event((0, "press", 0.0))
        logic.tick(3.0)
        logic.tick(4.0)
        self.assertEqual(calls, [1])


if __name__ == "__main__":
    unittest.main()
