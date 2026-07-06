"""MIDI foot controller application entrypoint.

Milestone 1: start under systemd, load config, and log a heartbeat to the
journal. Later milestones wire the placeholder modules into a real event loop.
"""

import logging
import queue
import signal
import subprocess
import sys
import time

from config.loader import load_config
from hardware import constants, sdnotify
from hardware.adc import ExpressionInput
from hardware.buttons import ButtonReader
from hardware.constants import BUTTON_NUM_POWER
from logic.actions import ActionLogic
from logic.expression import ExpressionLogic
from logic.menu import MenuLogic
from logic.midi_in import MidiInLogic
from logic.power import PowerLogic
from logic.settings import SettingsLogic
from midi.engine import MidiEngine
from state.manager import StateManager
from ui.renderer import UiRenderer
from web.server import WebServer

HEARTBEAT_SECONDS = 30.0
TICK_SECONDS = 0.01
# systemd watchdog: unit has WatchdogSec=30; ping well inside that so a hung
# main loop gets the service restarted.
WATCHDOG_PING_SECONDS = 10.0

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
    # The queue carries ("button", (num, kind, t)) and ("midi", message).
    events: queue.Queue = queue.Queue()
    midi = MidiEngine(state, config, on_message=lambda msg: events.put(("midi", msg)))
    ui = UiRenderer(state)
    web = WebServer(state)

    for module in (midi, ui, web):
        module.start()

    buttons = ButtonReader(config, lambda ev: events.put(("button", ev)))
    buttons.start()
    expression_input = ExpressionInput(config, state)
    expression_input.start()

    def shutdown_machine():
        # Safe power-off: systemd stops the service (SIGTERM -> clean module
        # shutdown) on the way down.
        subprocess.Popen(["sudo", "-n", "systemctl", "poweroff"])

    expression_logic = ExpressionLogic(config, state, midi)
    action_logic = ActionLogic(config, state, midi, expression_logic)
    menu_logic = MenuLogic(config, state, on_action_event=action_logic.on_button_event)
    power_logic = PowerLogic(config, state, on_shutdown=shutdown_machine)
    settings_logic = SettingsLogic(state, midi=midi)
    midi_in_logic = MidiInLogic(config, state)

    running = True

    def handle_signal(signum, frame):
        nonlocal running
        log.info("received %s, shutting down", signal.Signals(signum).name)
        running = False

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)
    # Debug: `kill -USR1 <pid>` saves the current frame to /tmp/controller-frame.png.
    signal.signal(signal.SIGUSR1, lambda s, f: ui.request_screenshot())

    sdnotify.notify("READY=1")

    next_heartbeat = 0.0
    next_watchdog = 0.0
    while running:
        try:
            event = events.get(timeout=TICK_SECONDS)
        except queue.Empty:
            event = None
        # One bad event or tick must not take the controller down mid-set:
        # log it and keep the loop alive (Milestone 16 crash recovery).
        try:
            if event is not None:
                source, payload = event
                if source == "midi":
                    midi_in_logic.handle_message(payload)
                elif payload[0] == BUTTON_NUM_POWER:
                    power_logic.handle_event(payload)
                elif state.settings_open:
                    settings_logic.handle_event(payload)
                else:
                    menu_logic.handle_event(payload)
            now = time.monotonic()
            menu_logic.tick(now)
            power_logic.tick(now)
            settings_logic.tick(now)
            action_logic.tick(now)
            expression_logic.tick(now)
            midi.tick(now)
        except Exception:
            log.exception("main loop error (event %r), continuing", event)
            now = time.monotonic()
        if now >= next_watchdog:
            sdnotify.notify("WATCHDOG=1")
            next_watchdog = now + WATCHDOG_PING_SECONDS
        if now >= next_heartbeat:
            log.info("heartbeat: menu %d", state.current_menu)
            next_heartbeat = now + HEARTBEAT_SECONDS

    sdnotify.notify("STOPPING=1")

    buttons.stop()
    expression_input.stop()
    for module in (web, ui, midi):
        module.stop()
    log.info("goodbye controller")
    return 0


if __name__ == "__main__":
    sys.exit(main())
