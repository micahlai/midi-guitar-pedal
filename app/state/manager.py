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
        # Buttons whose SECONDARY action fired and are still held — suppresses
        # the primary's pressed color after a hold fires.
        self.secondary_pressed: set[int] = set()
        # (menu_id, button_num) -> monotonic deadline: the action_cc secondary
        # on_color shows until this time (the slot's color_duration after the
        # hold fires — a hold fire has no natural "held" display period).
        self.secondary_color_until: dict[tuple[int, int], float] = {}
        # Buttons currently held toward a hold action (secondary, or shift ->
        # Menu 4 as button 10): num -> (pressed_at, hold_seconds). Drives the
        # hold progress bar (Milestone 13.5); cleared when the hold fires or
        # the button is released.
        self.hold_started: dict[int, tuple[float, float]] = {}
        # Tempo from incoming MIDI clock (Milestone 16 header); updated_at
        # lets the UI blank a stale readout when the clock stops.
        self.tempo_bpm: float | None = None
        self.tempo_updated_at = 0.0
        # Bumped on every config mutation (web edits, preset loads) so the
        # renderer's dirty check notices without hashing the whole config.
        self.config_version = 0
        # Boot screen: shown until main.py finishes startup (plus a minimum
        # on-screen time in the renderer). Messages appear bottom-left.
        self.booting = True
        self.boot_messages: list[str] = []
        self.settings_open = False
        self.settings_index = 0
        # Settings menu content (Milestone 15), owned by SettingsLogic; the
        # renderer only reads. View is "main" or "presets"; rows are the
        # (label, value) lines currently on screen.
        self.settings_view = "main"
        self.settings_rows: list[tuple[str, str]] = []
        self.settings_presets: list[str] = []
        # (config_version, mode) cache for the default expression scan.
        self._default_expression_cache: tuple[int, tuple | None] = (-1, None)

    def boot_log(self, message: str) -> None:
        """Append a startup progress line for the boot screen."""
        self.boot_messages = self.boot_messages + [message]  # atomic swap
        log.info("boot: %s", message)

    def install_config(self, new_config: dict) -> None:
        """Swap a whole new config (preset load/new/import, undo/redo) into
        the shared dict IN PLACE — modules hold references to the config
        object itself, so it must never be replaced wholesale."""
        for key in [k for k in self.config if k not in new_config]:
            del self.config[key]
        for key, value in new_config.items():
            self.config[key] = value
        # The active pot mode may now point at a slot that is no longer an
        # expression assignment; drop it rather than let ExpressionLogic read
        # expression fields off a foreign type.
        action = self.get_expression_action()
        if action is None or action.get("type") != "expression_pedal":
            self.expression_mode = None
        self.config_version += 1

    def effective_expression_mode(self) -> tuple[int, int, str] | None:
        """The assignment the pot currently drives: the selected mode, or the
        config's default expression assignment when none is selected."""
        if self.expression_mode is not None:
            return self.expression_mode
        from config.model import find_default_expression
        version, mode = self._default_expression_cache
        if version != self.config_version:
            mode = find_default_expression(self.config)
            self._default_expression_cache = (self.config_version, mode)
        return mode

    def get_expression_action(self) -> dict | None:
        from config.model import get_secondary_action, get_slot
        mode = self.effective_expression_mode()
        if mode is None:
            return None
        menu_id, button_num, role = mode
        slot = get_slot(self.config, menu_id, button_num)
        if slot is None:
            return None
        if role == "secondary":
            return get_secondary_action(slot)
        return slot.get("primary")
