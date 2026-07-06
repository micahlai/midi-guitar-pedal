"""Expression pedal value mapping and CC sending — pure logic.

Per docs/08_EXPRESSION_PEDAL_SPEC.md:
- normalized pot position (0.0-1.0, from hardware/adc.py via state) maps to
  the active mode's value_min..value_max, inverted when reverse is true,
  clamped to 0-127;
- sends the mode's CC when the mapped integer changes (deadband);
- when switching away from a mode that has a home value, exponentially walks
  its CC back to home (alpha per tick, stop threshold).
"""

import logging

log = logging.getLogger("controller.logic.expression")


def map_value(action: dict, normalized: float) -> int:
    lo, hi = action["value_min"], action["value_max"]
    frac = 1.0 - normalized if action.get("reverse") else normalized
    value = round(lo + (hi - lo) * frac)
    return max(0, min(127, value))


class ExpressionLogic:
    def __init__(self, config: dict, state, midi):
        self.state = state
        self.midi = midi
        exp = config["expression"]
        self.deadband = exp["send_deadband"]
        self.return_alpha = exp["return_alpha"]
        self.return_interval_s = exp["return_interval_ms"] / 1000.0
        self.return_stop = exp["return_stop_threshold"]
        self._last_sent: int | None = None
        # Active home-return jobs: (channel, cc) -> {"current": float, "home": int}
        self._returns: dict[tuple[int, int], dict] = {}
        self._next_return_at = 0.0

    def set_mode(self, mode: tuple[int, int]) -> None:
        """Switch the active expression assignment, starting a home-return for
        the previous one if it wants it."""
        previous = self.state.get_expression_action()
        if previous and previous.get("has_home") and self._last_sent is not None:
            key = (previous["midi_channel"], previous["cc_number"])
            self._returns[key] = {
                "current": float(self._last_sent),
                "home": previous["home_value"],
            }
            log.info("returning CC %s to home %d", key, previous["home_value"])
        self.state.expression_mode = mode
        self._last_sent = None

    def tick(self, t: float) -> None:
        self._send_pot()
        if t >= self._next_return_at:
            self._next_return_at = t + self.return_interval_s
            self._run_returns()

    def _send_pot(self) -> None:
        action = self.state.get_expression_action()
        if action is None or not self.state.expression_detected:
            return
        value = map_value(action, self.state.expression_value)
        if self._last_sent is not None and abs(value - self._last_sent) < self.deadband:
            return
        # A pot move onto a CC that was returning home cancels the return.
        self._returns.pop((action["midi_channel"], action["cc_number"]), None)
        self._last_sent = value
        self.midi.send_cc(action["midi_channel"], action["cc_number"], value)

    def _run_returns(self) -> None:
        for key in list(self._returns):
            job = self._returns[key]
            delta = job["home"] - job["current"]
            if abs(delta) < self.return_stop:
                self.midi.send_cc(key[0], key[1], job["home"])
                del self._returns[key]
                continue
            before = round(job["current"])
            job["current"] += delta * self.return_alpha
            after = round(job["current"])
            if after != before:
                self.midi.send_cc(key[0], key[1], after)
