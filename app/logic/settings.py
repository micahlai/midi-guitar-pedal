"""On-device settings menu navigation via footswitches — pure logic.

Placeholder content until Milestone 15 (wireless settings). Navigation per
docs/03_UI_SPEC.md: usable with only the 10 pushbuttons, labels on screen.

    B6 = up, B7 = down, B9 = select, B10 = exit
"""

import logging

log = logging.getLogger("controller.logic.settings")

SETTINGS_ITEMS = [
    "Wi-Fi status (stub)",
    "Bluetooth MIDI status (stub)",
    "USB MIDI status (stub)",
    "IP / hostname (stub)",
    "Pairing mode (stub)",
    "Exit",
]

BUTTON_UP = 6
BUTTON_DOWN = 7
BUTTON_SELECT = 9
BUTTON_EXIT = 10


class SettingsLogic:
    def __init__(self, state):
        self.state = state

    def handle_event(self, event: tuple) -> None:
        num, kind, _t = event
        if kind != "press":
            return
        if num == BUTTON_UP:
            self.state.settings_index = (self.state.settings_index - 1) % len(SETTINGS_ITEMS)
        elif num == BUTTON_DOWN:
            self.state.settings_index = (self.state.settings_index + 1) % len(SETTINGS_ITEMS)
        elif num == BUTTON_SELECT:
            item = SETTINGS_ITEMS[self.state.settings_index]
            if item == "Exit":
                self._close()
            else:
                log.info("settings: selected %r (stub)", item)
        elif num == BUTTON_EXIT:
            self._close()

    def _close(self) -> None:
        self.state.settings_open = False
        self.state.settings_index = 0
        log.info("settings closed")
