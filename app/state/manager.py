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
        # (menu_id, button_num, "primary"|"secondary") of the active
        # expression_pedal assignment.
        self.expression_mode: tuple[int, int, str] | None = None
        self.shift_held = False
        self.pressed_buttons: set[int] = set()  # physical buttons currently down
        # Buttons whose SECONDARY action fired and are still held — drives the
        # secondary on_color for action_cc secondaries.
        self.secondary_pressed: set[int] = set()
        # Buttons currently held toward a hold action (secondary, or shift ->
        # Menu 4 as button 10): num -> (pressed_at, hold_seconds). Drives the
        # hold progress bar (Milestone 13.5); cleared when the hold fires or
        # the button is released.
        self.hold_started: dict[int, tuple[float, float]] = {}
        self.settings_open = False
        self.settings_index = 0

    def get_expression_action(self) -> dict | None:
        from config.model import get_secondary_action, get_slot
        if self.expression_mode is None:
            return None
        menu_id, button_num, role = self.expression_mode
        slot = get_slot(self.config, menu_id, button_num)
        if slot is None:
            return None
        if role == "secondary":
            return get_secondary_action(slot)
        return slot.get("primary")
