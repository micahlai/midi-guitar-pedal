"""Placeholder configuration web server (Milestone 11)."""

import logging

from state.manager import StateManager

log = logging.getLogger("controller.web")


class WebServer:
    def __init__(self, state: StateManager):
        self.state = state

    def start(self) -> None:
        log.info("web server placeholder started (not listening yet)")

    def stop(self) -> None:
        log.info("web server placeholder stopped")
