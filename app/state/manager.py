"""State manager: the single source of truth for runtime state.

Inputs (future): button events, incoming MIDI, web config changes, ADC
values, expression detect changes, power button events.
Outputs (future): outgoing MIDI, UI updates, web live updates, saved state.
"""

import logging

log = logging.getLogger("controller.state")


class StateManager:
    def __init__(self, config: dict):
        self.config = config
        self.current_menu = 1
        self.current_program: int | None = None
        # effect_states[(channel, cc_number)] = bool, driven by MIDI feedback.
        self.effect_states: dict[tuple[int, int], bool] = {}
        self.expression_detected = False
        self.expression_value = 0.0  # normalized pot position 0.0-1.0
        # (menu_id, button_num) of the active expression_pedal assignment.
        self.expression_mode: tuple[int, int] | None = None
        self.shift_held = False
        self.pressed_buttons: set[int] = set()  # physical buttons currently down
        self.settings_open = False
        self.settings_index = 0

    def get_expression_action(self) -> dict | None:
        from config.model import get_primary
        if self.expression_mode is None:
            return None
        return get_primary(self.config, *self.expression_mode)
