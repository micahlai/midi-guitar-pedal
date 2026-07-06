"""MIDI engine: USB gadget send + receive (BLE lands in Milestone 14).

The Pi runs as a USB MIDI gadget (f_midi via configfs, see
scripts/setup-usb-midi-gadget.sh); mido/python-rtmidi opens the gadget's ALSA
port. Channels are 1-16 in config and converted to mido's 0-15 here.

Incoming messages are delivered on mido's callback thread to the on_message
callable (main.py points it at the thread-safe event queue).
"""

import logging
import threading

log = logging.getLogger("controller.midi")

PORT_NAME_HINT = "f_midi"


class MidiEngine:
    def __init__(self, state, config: dict | None = None, on_message=None):
        self.state = state
        self.config = config or state.config
        self.on_message = on_message or (lambda msg: None)
        self._out = None
        self._in = None
        self._lock = threading.Lock()

    def start(self) -> None:
        if not self.config["midi"]["usb_enabled"]:
            log.info("USB MIDI disabled in config")
            return
        try:
            import mido
        except ImportError as e:
            log.error("mido unavailable, MIDI disabled: %s", e)
            return
        try:
            names = mido.get_output_names()
        except Exception as e:
            log.error("MIDI backend unavailable: %s", e)
            return
        name = next((n for n in names if PORT_NAME_HINT in n), None)
        if name is None:
            log.error("USB MIDI gadget port not found (ports: %s) — "
                      "is usb-midi-gadget.service installed and dwc2 enabled?", names)
            return
        try:
            self._out = mido.open_output(name)
        except Exception as e:
            log.error("open MIDI output %r failed: %s", name, e)
            return
        log.info("MIDI output open: %s", name)
        try:
            self._in = mido.open_input(name, callback=self._on_incoming)
            log.info("MIDI input open: %s", name)
        except Exception as e:
            log.error("open MIDI input %r failed (send-only): %s", name, e)

    def _on_incoming(self, msg) -> None:
        if msg.type in ("control_change", "program_change", "note_on", "note_off"):
            log.info("MIDI in: %s", msg)
            self.on_message(msg)

    def stop(self) -> None:
        with self._lock:
            if self._in:
                self._in.close()
                self._in = None
            if self._out:
                self._out.close()
                self._out = None
        log.info("MIDI engine stopped")

    @property
    def connected(self) -> bool:
        return self._out is not None

    def send_cc(self, channel: int, cc: int, value: int) -> None:
        self._send("control_change", channel, control=cc, value=max(0, min(127, value)))

    def send_note(self, channel: int, note: int, velocity: int = 127) -> None:
        self._send("note_on", channel, note=max(0, min(127, note)),
                   velocity=max(0, min(127, velocity)))

    def send_program_change(self, channel: int, program: int) -> None:
        self._send("program_change", channel, program=max(0, min(127, program)))

    def _send(self, kind: str, channel: int, **fields) -> None:
        import mido
        msg = mido.Message(kind, channel=channel - 1, **fields)
        with self._lock:
            if self._out is None:
                log.debug("MIDI not connected, dropping %s", msg)
                return
            try:
                self._out.send(msg)
            except Exception as e:
                log.error("MIDI send failed: %s", e)
                return
        log.info("MIDI out: %s", msg)
