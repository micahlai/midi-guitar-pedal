"""Incoming MIDI -> state sync — pure logic (docs/04_MIDI_SPEC.md).

- Control Change / Note: for every effect_cc assignment matching channel +
  number (the cc_number field holds a note number for note-mapped rigs),
  update stored effect status: CC value 0 or note_off/velocity 0 = off,
  anything else = on. Status is keyed by (channel, number) in
  state.effect_states, so one message updates every assignment sharing it.
- Program Change: store the global current program (any channel), which
  program_change buttons compare against for their active color.
"""

import logging

from config.model import iter_effect_cc_actions

log = logging.getLogger("controller.logic.midi_in")


class MidiInLogic:
    def __init__(self, config: dict, state):
        self.config = config
        self.state = state

    def handle_message(self, msg) -> None:
        if msg.type == "control_change":
            self._handle_cc(msg.channel + 1, msg.control, msg.value)
        elif msg.type == "note_on":
            self._handle_cc(msg.channel + 1, msg.note, msg.velocity)
        elif msg.type == "note_off":
            self._handle_cc(msg.channel + 1, msg.note, 0)
        elif msg.type == "program_change":
            if self.state.current_program != msg.program:
                self.state.current_program = msg.program
                log.info("current program -> %d", msg.program)

    def _handle_cc(self, channel: int, cc: int, value: int) -> None:
        key = (channel, cc)
        if not any(
            action["midi_channel"] == channel and action["cc_number"] == cc
            for _menu, _btn, action in iter_effect_cc_actions(self.config)
        ):
            return  # feedback for a CC no effect assignment listens to
        on = value > 0
        if self.state.effect_states.get(key) != on:
            self.state.effect_states[key] = on
            log.info("effect CC %s -> %s", key, "on" if on else "off")
