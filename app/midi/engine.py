"""Placeholder MIDI engine: USB/BLE send + receive land in Milestones 7-8, 14."""

import logging

from state.manager import StateManager

log = logging.getLogger("controller.midi")


class MidiEngine:
    def __init__(self, state: StateManager):
        self.state = state

    def start(self) -> None:
        log.info("MIDI engine placeholder started (no ports opened yet)")

    def stop(self) -> None:
        log.info("MIDI engine placeholder stopped")
