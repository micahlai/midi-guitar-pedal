"""Shift/menu behavior and the button event model — pure logic, no hardware.

Consumes raw (button_num, "press"/"release", t) events plus tick(t) calls and
updates the StateManager. Per docs/06_BUTTON_MENU_LOGIC_SPEC.md:

- B10 short press/release: toggle Menu 1 <-> 2 (from Menu 3/4: back to Menu 1).
- B10 held for shift_hold_seconds: open Menu 4 (release then does nothing).
- B10 held + B5 press: open Menu 3; B5's own action is suppressed, including
  its release, and the shift hold timer is cancelled.
- B1-B9: press/release events (with timestamps) are handed to
  on_action_event; hold timing lives in logic/actions.py because secondary
  hold thresholds are per-slot.

Times are time.monotonic() seconds; tests pass synthetic values.
"""

import logging

SHIFT_BUTTON = 10
MENU3_COMBO_BUTTON = 5

log = logging.getLogger("controller.logic.menu")


class MenuLogic:
    def __init__(self, config: dict, state, on_action_event=None):
        self.state = state
        self.shift_hold_seconds = config["buttons"]["shift_hold_seconds"]
        # Called with (button_num, "press"|"release", t) for assignable
        # buttons that are not suppressed; logic/actions.py maps these to actions.
        self.on_action_event = on_action_event or (lambda num, kind, t: None)

        self._shift_down_at: float | None = None
        self._shift_consumed = False
        self._suppressed: set[int] = set()

    def handle_event(self, event: tuple) -> None:
        num, kind, t = event
        if num == SHIFT_BUTTON:
            self._handle_shift(kind, t)
        else:
            self._handle_assignable(num, kind, t)

    def tick(self, t: float) -> None:
        # Shift hold -> Menu 4.
        if (
            self._shift_down_at is not None
            and not self._shift_consumed
            and t - self._shift_down_at >= self.shift_hold_seconds
        ):
            self._shift_consumed = True
            self._set_menu(4, "shift hold")

    # --- internals ----------------------------------------------------------

    def _handle_shift(self, kind: str, t: float) -> None:
        if kind == "press":
            self._shift_down_at = t
            self._shift_consumed = False
            self.state.shift_held = True
            log.info("shift pressed")
        else:
            if self._shift_down_at is None:
                return  # orphaned release (debounce dropped the press)
            self.state.shift_held = False
            was_consumed = self._shift_consumed
            self._shift_down_at = None
            self._shift_consumed = False
            log.info("shift released")
            if not was_consumed:
                menu = self.state.current_menu
                self._set_menu(2 if menu == 1 else 1, "shift toggle")

    def _handle_assignable(self, num: int, kind: str, t: float) -> None:
        if kind == "press":
            if num == MENU3_COMBO_BUTTON and self._shift_down_at is not None:
                # Shift+B5 combo: Menu 3, no B5 action, no Menu 4 timer.
                self._shift_consumed = True
                self._suppressed.add(num)
                self._set_menu(3, "shift+B5")
                return
            log.info("B%d pressed", num)
            self.on_action_event(num, "press", t)
        else:
            if num in self._suppressed:
                self._suppressed.discard(num)
                return
            log.info("B%d released", num)
            self.on_action_event(num, "release", t)

    def _set_menu(self, menu: int, reason: str) -> None:
        if self.state.current_menu != menu:
            self.state.current_menu = menu
            log.info("menu -> %d (%s)", menu, reason)
