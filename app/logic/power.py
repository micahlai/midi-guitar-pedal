"""Power button behavior — pure logic, no hardware.

- Double press (two presses within power_double_press_ms): toggle the
  on-device settings menu.
- Hold for power_hold_seconds: safe shutdown — stubbed to a log line until
  power hardware exists (Milestone 16 / battery milestone).
- Single short press: nothing (hold is power on/off at the hardware level).
"""

import logging

log = logging.getLogger("controller.logic.power")


class PowerLogic:
    def __init__(self, config: dict, state):
        self.state = state
        self.double_press_s = config["buttons"]["power_double_press_ms"] / 1000.0
        self.hold_seconds = config["buttons"]["power_hold_seconds"]
        self._last_press_at: float | None = None
        self._down_at: float | None = None
        self._hold_fired = False

    def handle_event(self, event: tuple) -> None:
        _num, kind, t = event
        if kind == "press":
            self._down_at = t
            self._hold_fired = False
            if (
                self._last_press_at is not None
                and t - self._last_press_at <= self.double_press_s
            ):
                self._last_press_at = None
                self.state.settings_open = not self.state.settings_open
                self.state.settings_index = 0
                log.info("power double press: settings %s",
                         "opened" if self.state.settings_open else "closed")
            else:
                self._last_press_at = t
        else:
            self._down_at = None

    def tick(self, t: float) -> None:
        if (
            self._down_at is not None
            and not self._hold_fired
            and t - self._down_at >= self.hold_seconds
        ):
            self._hold_fired = True
            log.info("power hold %.1fs: shutdown requested (stub, no action)",
                     self.hold_seconds)
