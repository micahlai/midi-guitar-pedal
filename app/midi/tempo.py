"""Tempo from incoming MIDI clock (0xF8, 24 pulses per quarter note).

Pure logic: feed clock() monotonic timestamps from the MIDI input thread and
it returns the running BPM once enough pulses have arrived. A gap longer than
RESET_GAP_S (transport stopped / disconnected) restarts the measurement.
"""

import collections

PULSES_PER_BEAT = 24
RESET_GAP_S = 1.0
# Averaging window: 2 beats of pulses keeps the readout stable but still
# tracks tempo changes within a second.
WINDOW = PULSES_PER_BEAT * 2 + 1
MIN_PULSES = PULSES_PER_BEAT + 1  # one full beat before showing a number


class TempoTracker:
    def __init__(self):
        self._times: collections.deque = collections.deque(maxlen=WINDOW)

    def clock(self, now: float) -> float | None:
        """Register one MIDI clock pulse; returns the current BPM or None."""
        if self._times and now - self._times[-1] > RESET_GAP_S:
            self._times.clear()
        self._times.append(now)
        if len(self._times) < MIN_PULSES:
            return None
        span = self._times[-1] - self._times[0]
        if span <= 0:
            return None
        beats = (len(self._times) - 1) / PULSES_PER_BEAT
        return 60.0 * beats / span
