"""MIDI engine: USB gadget + BLE MIDI send/receive (Milestones 7, 8, 14).

USB: the Pi runs as a USB MIDI gadget (f_midi via configfs, see
scripts/setup-usb-midi-gadget.sh); mido/python-rtmidi opens the gadget's ALSA
port. BLE: midi/ble.py advertises the MIDI-over-BLE GATT service. Transports
are chosen with config midi.usb_enabled / midi.ble_enabled (both by default);
outgoing messages go to every enabled transport, incoming messages from
either arrive on the same on_message callback (delivered on that transport's
own thread; main.py points it at the thread-safe event queue).

Channels are 1-16 in config and converted to mido's 0-15 here.
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
        self._ble = None
        self._mido = None
        self._lock = threading.Lock()

    def start(self) -> None:
        try:
            import mido
        except ImportError as e:
            log.error("mido unavailable, MIDI disabled: %s", e)
            return
        self._mido = mido
        if self.config["midi"]["usb_enabled"]:
            self._start_usb(mido)
        else:
            log.info("USB MIDI disabled in config")
        if self.config["midi"]["ble_enabled"]:
            self._start_ble()
        else:
            log.info("BLE MIDI disabled in config")

    def _start_usb(self, mido) -> None:
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

    def _start_ble(self) -> None:
        from midi.ble import BleMidiServer
        ble = BleMidiServer(self.config["device"]["name"], self._on_ble_packet)
        if ble.start():
            self._ble = ble

    def _on_ble_packet(self, packet: bytes) -> None:
        from midi.ble_codec import decode_packet
        for midi_bytes in decode_packet(packet):
            try:
                msg = self._mido.Message.from_bytes(midi_bytes)
            except ValueError as e:
                log.warning("BLE MIDI: undecodable message %s: %s", midi_bytes, e)
                continue
            self._on_incoming(msg)

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
            if self._ble:
                self._ble.stop()
                self._ble = None
        log.info("MIDI engine stopped")

    @property
    def connected(self) -> bool:
        return self._out is not None or (self._ble is not None and self._ble.connected)

    @property
    def usb_open(self) -> bool:
        return self._out is not None

    @property
    def ble_state(self) -> str:
        """off | advertising | connected — shown in the settings menu."""
        if self._ble is None:
            return "off"
        return "connected" if self._ble.connected else "advertising"

    def send_cc(self, channel: int, cc: int, value: int) -> None:
        self._send("control_change", channel, control=cc, value=max(0, min(127, value)))

    def send_note(self, channel: int, note: int, velocity: int = 127) -> None:
        self._send("note_on", channel, note=max(0, min(127, note)),
                   velocity=max(0, min(127, velocity)))

    def send_program_change(self, channel: int, program: int) -> None:
        self._send("program_change", channel, program=max(0, min(127, program)))

    def _send(self, kind: str, channel: int, **fields) -> None:
        if self._mido is None:
            return
        msg = self._mido.Message(kind, channel=channel - 1, **fields)
        sent = []
        with self._lock:
            # midi.usb_enabled/ble_enabled are read live so the web toggles
            # mute a transport immediately (opening one needs a restart).
            if self._out is not None and self.config["midi"]["usb_enabled"]:
                try:
                    self._out.send(msg)
                    sent.append("usb")
                except Exception as e:
                    log.error("USB MIDI send failed: %s", e)
            if (self._ble is not None and self._ble.connected
                    and self.config["midi"]["ble_enabled"]):
                self._ble.send_midi(msg.bytes())
                sent.append("ble")
        if sent:
            log.info("MIDI out (%s): %s", "+".join(sent), msg)
        else:
            log.debug("MIDI not connected, dropping %s", msg)
