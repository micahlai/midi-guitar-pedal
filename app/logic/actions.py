"""Map assignable-button events to configured actions — pure logic.

Receives (button_num, "press"|"release", t) from MenuLogic for the CURRENT
menu. Dispatch per docs/07_ACTION_TYPES_SPEC.md; hold semantics per
docs/06_BUTTON_MENU_LOGIC_SPEC.md (Milestone 10):

- No secondary action: primary fires on press.
- Secondary exists: primary waits; released before the hold threshold ->
  primary fires on release; held past it (tick) -> secondary fires once and
  the release does nothing. Threshold is the slot's hold_seconds, falling
  back to buttons.secondary_hold_default_seconds.

Action dispatch (primary or secondary alike):
- effect_cc: send note_on velocity 127 (MainStage-style note mapping; the
  cc_number field holds the note number). Displayed state comes from
  feedback (M8) — CC or note, same number.
- action_cc: send note_on likewise; pressed visual via state.pressed_buttons.
- program_change: send PC; current program updates from feedback (M8).
- expression_pedal: select as active expression mode
  (state.expression_mode = (menu_id, button_num, "primary"|"secondary")).
- nothing: nothing.
"""

import logging

from config.model import get_secondary_action, get_slot

log = logging.getLogger("controller.logic.actions")


class ActionLogic:
    def __init__(self, config: dict, state, midi, expression=None):
        self.config = config
        self.state = state
        self.midi = midi
        self.expression = expression  # ExpressionLogic, for mode switches
        # Buttons waiting to resolve primary vs secondary:
        # num -> {"pressed_at": t, "slot": slot, "menu": menu_id}
        self._pending: dict[int, dict] = {}

    def on_button_event(self, num: int, kind: str, t: float) -> None:
        if kind == "press":
            self.state.pressed_buttons.add(num)
            self._on_press(num, t)
        elif kind == "release":
            self.state.pressed_buttons.discard(num)
            self._on_release(num)

    def tick(self, t: float) -> None:
        for num, pending in list(self._pending.items()):
            hold_s = pending["slot"]["secondary"].get(
                "hold_seconds", self.config["buttons"]["secondary_hold_default_seconds"]
            )
            if t - pending["pressed_at"] >= hold_s:
                del self._pending[num]
                secondary = get_secondary_action(pending["slot"])
                log.info("B%d hold: secondary fires", num)
                self._fire(pending["menu"], num, secondary, role="secondary")

    def _on_press(self, num: int, t: float) -> None:
        menu = self.state.current_menu
        slot = get_slot(self.config, menu, num)
        if slot is None or slot.get("primary") is None:
            log.info("B%d pressed: no assignment in menu %d", num, menu)
            return
        if get_secondary_action(slot):
            self._pending[num] = {"pressed_at": t, "slot": slot, "menu": menu}
        else:
            self._fire(menu, num, slot["primary"], role="primary")

    def _on_release(self, num: int) -> None:
        pending = self._pending.pop(num, None)
        if pending:  # released before the hold threshold -> primary
            self._fire(pending["menu"], num, pending["slot"]["primary"], role="primary")

    def _fire(self, menu: int, num: int, action: dict, role: str) -> None:
        kind = action.get("type")
        if kind in ("effect_cc", "action_cc"):
            self.midi.send_note(action["midi_channel"], action["cc_number"], 127)
        elif kind == "program_change":
            # Config stores the number as the user's rig displays it; the wire
            # value is offset by program_display_base (MainStage lists are
            # 1-based while MIDI PC is 0-based).
            base = self.config["midi"]["program_display_base"]
            wire = max(0, min(127, action["program_number"] - base))
            self.midi.send_program_change(action["midi_channel"], wire)
        elif kind == "expression_pedal":
            mode = (menu, num, role)
            if self.expression is not None:
                self.expression.set_mode(mode)
            else:
                self.state.expression_mode = mode
            log.info("expression mode -> %s (%s)", mode, action.get("label"))
        elif kind != "nothing":
            log.warning("B%d: unknown action type %r", num, kind)
