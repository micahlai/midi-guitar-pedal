"""MIDI foot controller application entrypoint.

Milestone 1: start under systemd, load config, and log a heartbeat to the
journal. Later milestones wire the placeholder modules into a real event loop.
"""

import logging
import signal
import sys
import time

from config.loader import load_config
from hardware import constants
from midi.engine import MidiEngine
from state.manager import StateManager
from ui.renderer import UiRenderer
from web.server import WebServer

HEARTBEAT_SECONDS = 5.0

log = logging.getLogger("controller")


def main() -> int:
    logging.basicConfig(
        stream=sys.stdout,
        level=logging.INFO,
        format="%(name)s: %(message)s",
    )
    log.info("hello controller")
    log.info(
        "buttons on GPIO %s, shift on GPIO %d",
        constants.GPIO_ASSIGNABLE_BUTTONS,
        constants.GPIO_BUTTON_10_SHIFT,
    )

    config = load_config()
    log.info("config version %d loaded for %s", config["version"], config["device"]["name"])

    state = StateManager(config)
    midi = MidiEngine(state)
    ui = UiRenderer(state)
    web = WebServer(state)

    for module in (midi, ui, web):
        module.start()

    running = True

    def handle_signal(signum, frame):
        nonlocal running
        log.info("received %s, shutting down", signal.Signals(signum).name)
        running = False

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    while running:
        log.info("heartbeat: menu %d", state.current_menu)
        time.sleep(HEARTBEAT_SECONDS)

    for module in (web, ui, midi):
        module.stop()
    log.info("goodbye controller")
    return 0


if __name__ == "__main__":
    sys.exit(main())
