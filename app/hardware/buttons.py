"""GPIO footswitch reading (gpiozero) — hardware only, no menu/action logic.

Buttons are wired between GPIO and GND with internal pull-ups (pressed reads
low). Events are (button_num, "press" | "release", monotonic_time) tuples
handed to a callback from gpiozero's callback threads; the consumer is
expected to be a thread-safe queue.

Debounce is done here in software: gpiozero's bounce_time is broken on the
lgpio pin factory (it silently drops all events), so Buttons are created
without it and edges within debounce_ms of the last accepted edge are
ignored, with same-state edges deduplicated.

Every edge (accepted or debounced) also arms a one-shot reconcile timer that
reads the REAL pin level just after the debounce window and emits a
corrective event if the tracked state drifted. Without it, a genuine release
landing inside the window was swallowed for good: the reader kept thinking
"pressed", the next physical press was deduped as a repeat, and every event
from then on arrived inverted.
"""

import logging
import threading
import time

from hardware.constants import BUTTON_NUM_POWER, GPIO_BY_BUTTON, GPIO_POWER_BUTTON

# All watched inputs: footswitches B1-B10 plus the power button.
WATCHED_PINS = {**GPIO_BY_BUTTON, BUTTON_NUM_POWER: GPIO_POWER_BUTTON}

log = logging.getLogger("controller.hw.buttons")

# Read the pin level this long after the debounce window closes — the
# contacts have settled by then, so the level is trustworthy.
RECONCILE_MARGIN_S = 0.005


class ButtonReader:
    def __init__(self, config: dict, on_event):
        self.debounce_s = config["buttons"]["debounce_ms"] / 1000.0
        self.on_event = on_event
        self._buttons: dict[int, object] = {}
        self._last_t: dict[int, float] = {}
        self._last_kind: dict[int, str] = {}
        self._timers: dict[int, object] = {}
        self._lock = threading.Lock()

    def _edge(self, num: int, kind: str) -> None:
        t = time.monotonic()
        with self._lock:
            accepted = (self._last_kind.get(num, "release") != kind
                        and t - self._last_t.get(num, -1.0) >= self.debounce_s)
            if accepted:
                self._last_t[num] = t
                self._last_kind[num] = kind
            self._schedule_reconcile(num)
        if accepted:
            self.on_event((num, kind, t))

    def _schedule_reconcile(self, num: int) -> None:
        """One pending timer per pin, checking the level after the window.
        Caller holds the lock."""
        if self._timers.get(num) is not None:
            return
        timer = threading.Timer(self.debounce_s + RECONCILE_MARGIN_S,
                                self._reconcile, args=(num,))
        timer.daemon = True
        self._timers[num] = timer
        timer.start()

    def _reconcile(self, num: int) -> None:
        """Timer thread: emit a corrective event when the tracked state no
        longer matches the physical pin (the matching edge was debounced)."""
        emit = None
        with self._lock:
            self._timers[num] = None
            kind = "press" if self._pin_pressed(num) else "release"
            if self._last_kind.get(num, "release") == kind:
                return
            t = time.monotonic()
            if t - self._last_t.get(num, -1.0) < self.debounce_s:
                self._schedule_reconcile(num)  # still settling; look again
                return
            self._last_t[num] = t
            self._last_kind[num] = kind
            emit = (num, kind, t)
        log.debug("button %d reconciled to %s (edge was debounced)", num, kind)
        self.on_event(emit)

    def _pin_pressed(self, num: int) -> bool:
        button = self._buttons.get(num)
        if button is None:  # closed while a timer was in flight
            return self._last_kind.get(num, "release") == "press"
        return bool(button.is_pressed)

    def start(self) -> bool:
        try:
            from gpiozero import Button
        except ImportError as e:
            log.error("gpiozero unavailable, buttons disabled: %s", e)
            return False

        def make_handlers(num):
            return (
                lambda: self._edge(num, "press"),
                lambda: self._edge(num, "release"),
            )

        try:
            for num, pin in WATCHED_PINS.items():
                button = Button(pin, pull_up=True)
                button.when_pressed, button.when_released = make_handlers(num)
                self._buttons[num] = button
        except Exception as e:
            log.error("GPIO init failed, buttons disabled: %s", e)
            self.stop()
            return False

        log.info("watching %d buttons, debounce %.0f ms",
                 len(self._buttons), self.debounce_s * 1000)
        return True

    def stop(self) -> None:
        with self._lock:
            for timer in self._timers.values():
                if timer is not None:
                    timer.cancel()
            self._timers = {}
            buttons, self._buttons = self._buttons, {}
        for button in buttons.values():
            button.close()
