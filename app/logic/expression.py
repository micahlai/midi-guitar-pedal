"""Expression pedal value mapping and CC sending — pure logic.

Per docs/08_EXPRESSION_PEDAL_SPEC.md:
- normalized pot position (0.0-1.0, from hardware/adc.py via state) maps to
  the active mode's value_min..value_max, inverted when reverse is true,
  clamped to 0-127;
- sends the mode's CC when the mapped integer changes (deadband);
- when switching away from a mode that has a home value, exponentially walks
  its CC back to home (return_alpha per tick, return_stop_threshold);
- when switching ONTO a mode, its select_mode decides what happens if the pot
  is not where that mode's CC was left (Milestone 17):
    snap        - the CC jumps to the pot's value
    catch       - the CC is held still until the pot sweeps through it, so it
                  moves only once pot and CC agree (no jump)
    interpolate - the CC glides exponentially to the pot's value, same curve
                  as the home-return, then tracks the pot

All five of those live on the ACTION, not in config["expression"], so each
effect can behave differently and the behavior travels with the preset. They
are read through _setting() so configs written before Milestone 17 (and actions
the web app has not re-saved) fall back to ACTION_DEFAULTS. Which action owns a
setting matters: a home-return uses the settings of the effect being LEFT (it is
that effect's CC walking home), while select_* come from the effect being
ENTERED.

Both catch and interpolate need to know where a CC was left, so every value
this module sends is remembered per (channel, cc) in self._values. A CC that
is mid home-return when it is selected again freezes where it is — that frozen
value, not the home value, is what the pot has to catch or glide from.
"""

import logging

log = logging.getLogger("controller.logic.expression")

SELECT_MODES = ("snap", "catch", "interpolate")

# Per-action expression settings (preset-scoped) and their fallbacks.
ACTION_DEFAULTS = {
    "select_mode": "snap",
    "return_alpha": 0.15,
    "return_stop_threshold": 0.5,
    "select_alpha": 0.15,
    "select_stop_threshold": 0.5,
}


def map_value(action: dict, normalized: float) -> int:
    lo, hi = action["value_min"], action["value_max"]
    frac = 1.0 - normalized if action.get("reverse") else normalized
    value = round(lo + (hi - lo) * frac)
    return max(0, min(127, value))


def setting(action: dict | None, name: str):
    """One of the per-action expression settings, defaulted for actions that
    predate it. select_mode is additionally guarded against junk in a
    hand-edited config, since it selects a code path."""
    value = (action or {}).get(name, ACTION_DEFAULTS[name])
    if name == "select_mode" and value not in SELECT_MODES:
        return ACTION_DEFAULTS["select_mode"]
    return value


class ExpressionLogic:
    def __init__(self, config: dict, state, midi):
        self.config = config
        self.state = state
        self.midi = midi
        exp = config["expression"]
        self.deadband = exp["send_deadband"]
        # The tick rate of both the home-return and the on-selection glide stays
        # device-wide: it is how often we can send, not how the effect behaves.
        self.return_interval_s = exp["return_interval_ms"] / 1000.0
        self._last_sent: int | None = None
        # Active home-return jobs, each carrying the speed/threshold of the
        # action that started it: (channel, cc) -> {"current", "home", "alpha",
        # "stop"}. The action itself may be edited (or gone) before the job
        # finishes, so the job does not read back from it.
        self._returns: dict[tuple[int, int], dict] = {}
        # Last value sent per (channel, cc), across mode switches — where a CC
        # was left, which is what catch/interpolate pick up from.
        self._values: dict[tuple[int, int], float] = {}
        # Set by set_mode when the newly selected CC must reach the pot before
        # it starts tracking it: {"mode": catch|interpolate, "key", ...}.
        self._pending: dict | None = None
        self._next_return_at = 0.0

    # --- config read live, so the web app's changes take effect immediately ---

    @property
    def retain_value(self) -> bool:
        return bool(self.config["expression"].get("retain_pedal_value"))

    def _pedal_usable(self) -> bool:
        """With retain_pedal_value the pot keeps its last reading when the pedal
        is unplugged (hardware/adc.py stops updating it), so the active mode
        stays parked at that value rather than going dead."""
        return self.state.expression_detected or self.retain_value

    # --- mode switching -------------------------------------------------------

    def set_mode(self, mode: tuple[int, int, str]) -> None:
        """Switch the active expression assignment: start a home-return for the
        mode we are leaving, then decide how the mode we are entering meets the
        pot (see select_mode)."""
        self._start_home_return(self.state.get_expression_action())
        self.state.expression_mode = mode
        self._last_sent = None
        self._set_pending(None)

        action = self.state.get_expression_action()
        if action is None:
            self.state.expression_sent_value = None
            return
        key = (action["midi_channel"], action["cc_number"])
        # Selecting a CC that is walking home stops it where it is — that is the
        # value the pot now has to meet, not the home value it was heading for.
        job = self._returns.pop(key, None)
        held = job["current"] if job else self._values.get(key)
        select = setting(action, "select_mode")
        self.state.expression_sent_value = None if held is None else round(held)
        if held is None or select == "snap":
            return  # nothing to meet: the pot's value applies immediately
        self._values[key] = float(held)
        if select == "catch":
            target = round(held)
            # Which side of the effect the pedal is on right now decides which
            # way it has to sweep to catch it. Fixed here, at selection: read
            # later it would already have moved, and a pedal that had crossed
            # in the meantime would look like it was approaching from the far
            # side and never catch at all.
            side = map_value(action, self.state.expression_value) - target
            if side == 0:
                return  # already together: track the pedal straight away
            self._set_pending({
                "mode": "catch", "key": key, "target": target, "side": side,
            })
            log.info("CC %s held at %d until the pot reaches it", key, target)
        else:
            self._set_pending({
                "mode": "interpolate", "key": key, "current": float(held),
                "alpha": setting(action, "select_alpha"),
                "stop": setting(action, "select_stop_threshold"),
            })
            log.info("CC %s interpolating from %d to the pot", key, round(held))

    def _set_pending(self, pending: dict | None) -> None:
        """The UI's red pedal marker hangs off this: it shows only while the
        selected effect is still meeting the pedal, and goes away for good once
        they meet — until another effect is selected."""
        self._pending = pending
        self.state.expression_meeting_pedal = pending is not None

    def _start_home_return(self, action: dict | None) -> None:
        if not action or not action.get("has_home"):
            return
        key = (action["midi_channel"], action["cc_number"])
        current = self._values.get(key)
        # Nothing sent on this CC yet (fresh boot), or it is already home.
        if current is None or round(current) == action["home_value"]:
            return
        self._returns[key] = {
            "current": float(current), "home": action["home_value"],
            "alpha": setting(action, "return_alpha"),
            "stop": setting(action, "return_stop_threshold"),
        }
        log.info("returning CC %s to home %d", key, action["home_value"])

    # --- tick -----------------------------------------------------------------

    def tick(self, t: float) -> None:
        if t >= self._next_return_at:
            self._next_return_at = t + self.return_interval_s
            self._run_returns()
            self._run_interpolation()
        self._send_pot()

    def _send_pot(self) -> None:
        action = self.state.get_expression_action()
        if action is None or not self._pedal_usable():
            return
        key = (action["midi_channel"], action["cc_number"])
        value = map_value(action, self.state.expression_value)
        if self._pending is not None:
            # An interpolation is driven by the tick below, not by the pot.
            if self._pending["mode"] == "interpolate" or not self._catch_reached(value):
                return
            log.info("CC %s caught at %d; tracking the pot", key, value)
            self._set_pending(None)
        elif self._last_sent is not None and abs(value - self._last_sent) < self.deadband:
            return
        # A pot move onto a CC that was returning home cancels the return.
        self._returns.pop(key, None)
        self._last_sent = value
        self._send(key, value)

    def _catch_reached(self, value: int) -> bool:
        """True once the pedal has swept onto — or through — the value the CC
        was left at, coming from the side it was on when the effect was
        selected."""
        pending = self._pending
        difference = value - pending["target"]
        return difference == 0 or (difference > 0) != (pending["side"] > 0)

    def _run_returns(self) -> None:
        for key in list(self._returns):
            job = self._returns[key]
            delta = job["home"] - job["current"]
            if abs(delta) < job["stop"]:
                self._send(key, job["home"])
                del self._returns[key]
                continue
            before = round(job["current"])
            job["current"] += delta * job["alpha"]
            after = round(job["current"])
            if after != before:
                self._send(key, after)

    def _run_interpolation(self) -> None:
        """Walk the just-selected CC toward the live pot value; once it is within
        select_stop_threshold, _send_pot takes over and tracks the pot exactly."""
        pending = self._pending
        if pending is None or pending["mode"] != "interpolate":
            return
        action = self.state.get_expression_action()
        if action is None or not self._pedal_usable():
            return
        target = map_value(action, self.state.expression_value)
        delta = target - pending["current"]
        if abs(delta) < pending["stop"]:
            log.info("CC %s reached the pot; tracking it", pending["key"])
            self._set_pending(None)
            return
        before = round(pending["current"])
        pending["current"] += delta * pending["alpha"]
        after = round(pending["current"])
        if after != before:
            self._send(pending["key"], after)

    def _send(self, key: tuple[int, int], value: int) -> None:
        """Every send goes through here so _values always knows where a CC was
        left — that is what a later selection catches or interpolates from."""
        self._values[key] = float(value)
        if key == self._active_key():
            self.state.expression_sent_value = value
        self.midi.send_cc(key[0], key[1], value)

    def _active_key(self) -> tuple[int, int] | None:
        action = self.state.get_expression_action()
        if action is None:
            return None
        return (action["midi_channel"], action["cc_number"])
