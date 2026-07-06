"""MIDI foot controller application entrypoint.

Milestone 1: start under systemd, load config, and log a heartbeat to the
journal. Later milestones wire the placeholder modules into a real event loop.
"""

import logging
import queue
import signal
import sys
import time

from config.loader import load_config
from hardware import constants
from hardware.adc import ExpressionInput
from hardware.buttons import ButtonReader
from hardware.constants import BUTTON_NUM_POWER
from logic.actions import ActionLogic
from logic.expression import ExpressionLogic
from logic.menu import MenuLogic
from logic.power import PowerLogic
from logic.settings import SettingsLogic
from midi.engine import MidiEngine
from state.manager import StateManager
from ui.renderer import UiRenderer
from web.server import WebServer

HEARTBEAT_SECONDS = 30.0
TICK_SECONDS = 0.01

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
    midi = MidiEngine(state, config)
    ui = UiRenderer(state)
    web = WebServer(state)

    for module in (midi, ui, web):
        module.start()

    events: queue.Queue = queue.Queue()
    buttons = ButtonReader(config, events.put)
    buttons.start()
    expression_input = ExpressionInput(config, state)
    expression_input.start()

    expression_logic = ExpressionLogic(config, state, midi)
    action_logic = ActionLogic(config, state, midi, expression_logic)
    menu_logic = MenuLogic(config, state, on_action_event=action_logic.on_button_event)
    power_logic = PowerLogic(config, state)
    settings_logic = SettingsLogic(state)

    running = True

    def handle_signal(signum, frame):
        nonlocal running
        log.info("received %s, shutting down", signal.Signals(signum).name)
        running = False

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)
    # Debug: `kill -USR1 <pid>` saves the current frame to /tmp/controller-frame.png.
    signal.signal(signal.SIGUSR1, lambda s, f: ui.request_screenshot())

    next_heartbeat = 0.0
    while running:
        try:
            event = events.get(timeout=TICK_SECONDS)
        except queue.Empty:
            event = None
        if event is not None:
            if event[0] == BUTTON_NUM_POWER:
                power_logic.handle_event(event)
            elif state.settings_open:
                settings_logic.handle_event(event)
            else:
                menu_logic.handle_event(event)
        now = time.monotonic()
        menu_logic.tick(now)
        power_logic.tick(now)
        expression_logic.tick(now)
        if now >= next_heartbeat:
            log.info("heartbeat: menu %d", state.current_menu)
            next_heartbeat = now + HEARTBEAT_SECONDS

    buttons.stop()
    expression_input.stop()
    for module in (web, ui, midi):
        module.stop()
    log.info("goodbye controller")
    return 0


if __name__ == "__main__":
    sys.exit(main())
