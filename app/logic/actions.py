"""Map assignable-button events to configured actions — pure logic.

Receives (button_num, "press"|"release"|"hold") from MenuLogic for the
CURRENT menu and dispatches per docs/07_ACTION_TYPES_SPEC.md. Milestone 10
adds the secondary-hold semantics; for now the primary fires on press.

- effect_cc: send CC value 127 on press; displayed state only updates from
  incoming feedback (Milestone 8).
- action_cc: send CC on press; pressed visual tracked via state.pressed_buttons.
- program_change: send PC; current program updates from feedback (Milestone 8).
- expression_pedal: select this assignment as the active expression mode.
- nothing: nothing.
"""

import logging

from config.model import get_primary

log = logging.getLogger("controller.logic.actions")


class ActionLogic:
    def __init__(self, config: dict, state, midi, expression=None):
        self.config = config
        self.state = state
        self.midi = midi
        self.expression = expression  # ExpressionLogic, for mode switches

    def on_button_event(self, num: int, kind: str) -> None:
        if kind == "press":
            self.state.pressed_buttons.add(num)
        elif kind == "release":
            self.state.pressed_buttons.discard(num)

        if kind != "press":
            return  # hold/release semantics arrive with Milestone 10

        primary = get_primary(self.config, self.state.current_menu, num)
        if primary is None:
            log.info("B%d pressed: no assignment in menu %d", num, self.state.current_menu)
            return
        kind_ = primary.get("type")
        if kind_ == "effect_cc":
            self.midi.send_cc(primary["midi_channel"], primary["cc_number"], 127)
        elif kind_ == "action_cc":
            self.midi.send_cc(primary["midi_channel"], primary["cc_number"], 127)
        elif kind_ == "program_change":
            self.midi.send_program_change(primary["midi_channel"], primary["program_number"])
        elif kind_ == "expression_pedal":
            mode = (self.state.current_menu, num)
            if self.expression is not None:
                self.expression.set_mode(mode)
            else:
                self.state.expression_mode = mode
            log.info("expression mode -> %s (%s)", mode, primary.get("label"))
        elif kind_ != "nothing":
            log.warning("B%d: unknown action type %r", num, kind_)
