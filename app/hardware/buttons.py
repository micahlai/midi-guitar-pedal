"""GPIO footswitch reading (gpiozero) — hardware only, no menu/action logic.

Buttons are wired between GPIO and GND with internal pull-ups (pressed reads
low). Events are (button_num, "press" | "release", monotonic_time) tuples
handed to a callback from gpiozero's callback threads; the consumer is
expected to be a thread-safe queue.

Debounce is done here in software: gpiozero's bounce_time is broken on the
lgpio pin factory (it silently drops all events), so Buttons are created
without it and edges within debounce_ms of the last accepted edge are
ignored, with same-state edges deduplicated.
"""

import logging
import time

from hardware.constants import GPIO_BY_BUTTON

log = logging.getLogger("controller.hw.buttons")


class ButtonReader:
    def __init__(self, config: dict, on_event):
        self.debounce_s = config["buttons"]["debounce_ms"] / 1000.0
        self.on_event = on_event
        self._buttons = []
        self._last_t: dict[int, float] = {}
        self._last_kind: dict[int, str] = {}

    def _edge(self, num: int, kind: str) -> None:
        t = time.monotonic()
        if self._last_kind.get(num) == kind:
            return
        if t - self._last_t.get(num, -1.0) < self.debounce_s:
            return
        self._last_t[num] = t
        self._last_kind[num] = kind
        self.on_event((num, kind, t))

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
            for num, pin in GPIO_BY_BUTTON.items():
                button = Button(pin, pull_up=True)
                button.when_pressed, button.when_released = make_handlers(num)
                self._buttons.append(button)
        except Exception as e:
            log.error("GPIO init failed, buttons disabled: %s", e)
            self.stop()
            return False

        log.info("watching %d buttons, debounce %.0f ms",
                 len(self._buttons), self.debounce_s * 1000)
        return True

    def stop(self) -> None:
        for button in self._buttons:
            button.close()
        self._buttons = []
