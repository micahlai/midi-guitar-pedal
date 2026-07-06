"""Placeholder 1920x480 fullscreen UI renderer (Milestone 2)."""

import logging

from state.manager import StateManager

log = logging.getLogger("controller.ui")


class UiRenderer:
    def __init__(self, state: StateManager):
        self.state = state

    def start(self) -> None:
        log.info("UI renderer placeholder started (no display output yet)")

    def stop(self) -> None:
        log.info("UI renderer placeholder stopped")
