"""BLE MIDI peripheral via BlueZ D-Bus (Milestone 14).

Registers the standard MIDI-over-BLE GATT service and an LE advertisement so
DAW hosts (MainStage via Audio MIDI Setup's Bluetooth panel) can connect
wirelessly. Runs a GLib main loop in a daemon thread; needs the apt packages
python3-dbus and python3-gi (venv is --system-site-packages).

Outgoing messages are sent as notifications on the MIDI characteristic;
incoming writes are decoded (midi/ble_codec.py) and handed to on_bytes on
GLib's thread — the caller adapts them onto its own queue.

Everything degrades gracefully: missing dbus modules, no adapter, or a
bluetoothd without GATT/advertising managers logs an error and leaves the
controller running USB-only.
"""

import logging
import subprocess
import threading
import time

log = logging.getLogger("controller.midi.ble")

from midi.ble_codec import decode_packet, encode_message

MIDI_SERVICE_UUID = "03b80e5a-ede8-4b33-a751-6ce34ec4c700"
MIDI_CHAR_UUID = "7772e5db-3868-4112-a1a9-f2669d106bf3"

BLUEZ = "org.bluez"
GATT_MANAGER = "org.bluez.GattManager1"
AD_MANAGER = "org.bluez.LEAdvertisingManager1"
ADAPTER = "org.bluez.Adapter1"
OM_IFACE = "org.freedesktop.DBus.ObjectManager"
PROPS_IFACE = "org.freedesktop.DBus.Properties"
SERVICE_IFACE = "org.bluez.GattService1"
CHAR_IFACE = "org.bluez.GattCharacteristic1"
AD_IFACE = "org.bluez.LEAdvertisement1"

BASE_PATH = "/com/midicontroller"


def _build_classes(dbus, dbus_service):
    """dbus.service.Object subclasses, built lazily so importing this module
    never requires dbus (tests / machines without BlueZ)."""

    class Application(dbus_service.Object):
        def __init__(self, bus, service):
            self.path = BASE_PATH
            self.service = service
            super().__init__(bus, self.path)

        @dbus_service.method(OM_IFACE, out_signature="a{oa{sa{sv}}}")
        def GetManagedObjects(self):
            char = self.service.characteristic
            return {
                self.service.path: {SERVICE_IFACE: self.service.properties()},
                char.path: {CHAR_IFACE: char.properties()},
            }

    class MidiService(dbus_service.Object):
        def __init__(self, bus):
            self.path = BASE_PATH + "/service0"
            self.characteristic = None  # set by owner
            super().__init__(bus, self.path)

        def properties(self):
            return {
                "UUID": MIDI_SERVICE_UUID,
                "Primary": dbus.Boolean(True),
            }

    class MidiCharacteristic(dbus_service.Object):
        def __init__(self, bus, service, on_bytes):
            self.path = service.path + "/char0"
            self.service_path = service.path
            self.on_bytes = on_bytes
            self.notifying = False
            super().__init__(bus, self.path)

        def properties(self):
            return {
                "Service": dbus.ObjectPath(self.service_path),
                "UUID": MIDI_CHAR_UUID,
                "Flags": dbus.Array(
                    ["read", "write-without-response", "write", "notify"],
                    signature="s"),
            }

        @dbus_service.method(CHAR_IFACE, in_signature="a{sv}", out_signature="ay")
        def ReadValue(self, options):
            return dbus.Array([], signature="y")  # per BLE-MIDI spec

        @dbus_service.method(CHAR_IFACE, in_signature="aya{sv}")
        def WriteValue(self, value, options):
            self.on_bytes(bytes(value))

        @dbus_service.method(CHAR_IFACE)
        def StartNotify(self):
            self.notifying = True
            log.info("BLE MIDI central subscribed")

        @dbus_service.method(CHAR_IFACE)
        def StopNotify(self):
            self.notifying = False
            log.info("BLE MIDI central unsubscribed")

        def send(self, packet: bytes):
            if not self.notifying:
                return
            self.PropertiesChanged(
                CHAR_IFACE,
                {"Value": dbus.Array(packet, signature="y")}, [])

        @dbus_service.signal(PROPS_IFACE, signature="sa{sv}as")
        def PropertiesChanged(self, interface, changed, invalidated):
            pass

    class Advertisement(dbus_service.Object):
        def __init__(self, bus, name):
            self.path = BASE_PATH + "/advertisement0"
            self.name = name
            super().__init__(bus, self.path)

        @dbus_service.method(PROPS_IFACE, in_signature="s", out_signature="a{sv}")
        def GetAll(self, interface):
            return {
                "Type": "peripheral",
                "ServiceUUIDs": dbus.Array([MIDI_SERVICE_UUID], signature="s"),
                "LocalName": dbus.String(self.name),
                "Discoverable": dbus.Boolean(True),
            }

        @dbus_service.method("org.bluez.LEAdvertisement1")
        def Release(self):
            log.info("BLE advertisement released by bluetoothd")

    return Application, MidiService, MidiCharacteristic, Advertisement


class BleMidiServer:
    """Owns the GLib thread, the GATT app and the advertisement."""

    def __init__(self, device_name: str, on_bytes):
        self.device_name = device_name
        self.on_bytes = on_bytes  # called with raw incoming BLE-MIDI packets
        self._char = None
        self._glib = None
        self._loop = None
        self._thread: threading.Thread | None = None
        self._started_at = time.monotonic()
        self._legacy_instance: int | None = None  # btmgmt fallback ad instance

    # --- lifecycle (called from the main thread) ---------------------------

    def start(self) -> bool:
        try:
            import dbus
            import dbus.mainloop.glib
            import dbus.service
            from gi.repository import GLib
        except ImportError as e:
            log.error("BLE MIDI unavailable (install python3-dbus python3-gi): %s", e)
            return False
        self._glib = GLib
        try:
            dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
            bus = dbus.SystemBus()
            adapter_path = self._find_adapter(dbus, bus)
            if adapter_path is None:
                log.error("no Bluetooth adapter with GATT support found")
                return False

            adapter_props = dbus.Interface(bus.get_object(BLUEZ, adapter_path), PROPS_IFACE)
            adapter_props.Set(ADAPTER, "Powered", dbus.Boolean(True))
            adapter_props.Set(ADAPTER, "Alias", dbus.String(self.device_name))

            App, Service, Char, Ad = _build_classes(dbus, dbus.service)
            service = Service(bus)
            self._char = Char(bus, service, self._on_write)
            service.characteristic = self._char
            app = App(bus, service)
            ad = Ad(bus, self.device_name)

            gatt = dbus.Interface(bus.get_object(BLUEZ, adapter_path), GATT_MANAGER)
            gatt.RegisterApplication(
                app.path, {},
                reply_handler=lambda: log.info("BLE MIDI GATT service registered"),
                error_handler=lambda e: log.error("GATT registration failed: %s", e))
            ads = dbus.Interface(bus.get_object(BLUEZ, adapter_path), AD_MANAGER)
            ads.RegisterAdvertisement(
                ad.path, {},
                reply_handler=lambda: log.info(
                    "BLE MIDI advertising as %r", self.device_name),
                error_handler=self._advertising_failed)
        except Exception as e:
            log.error("BLE MIDI setup failed: %s", e)
            return False

        self._loop = GLib.MainLoop()
        self._thread = threading.Thread(target=self._loop.run, name="ble-midi", daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        if self._legacy_instance is not None:
            self._btmgmt("rm-adv", str(self._legacy_instance))
            self._legacy_instance = None
        if self._loop is not None:
            self._loop.quit()
            self._loop = None
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def _advertising_failed(self, error) -> None:
        """bluetoothd 5.82 registers ads with the kernel's EXTENDED
        advertising MGMT commands, which kernel 6.18 rejects (Invalid
        Parameters) on the Zero 2 W's legacy-only radio. The legacy
        `btmgmt add-adv` path works, so fall back to it: a connectable,
        general-discoverable instance carrying the MIDI service UUID.
        Connections still land on the bluetoothd-served GATT app."""
        log.warning("D-Bus advertising failed (%s); trying btmgmt fallback", error)
        self._btmgmt("add-adv", "-c", "-g", "-u", MIDI_SERVICE_UUID, "1")
        # btmgmt produces no output and never exits cleanly when piped, so
        # confirm through the adapter's ActiveInstances count instead.
        if self._advertising_active():
            self._legacy_instance = 1
            log.info("BLE MIDI advertising via btmgmt (legacy) as %r", self.device_name)
        else:
            log.error("btmgmt advertising fallback failed (no active instances)")

    @staticmethod
    def _btmgmt(*args) -> None:
        """Fire a btmgmt command; effects are checked out-of-band because the
        tool blocks forever on a pipe (hence the hard timeout)."""
        try:
            subprocess.run(["sudo", "-n", "timeout", "5", "btmgmt", *args],
                           capture_output=True, stdin=subprocess.DEVNULL, timeout=15)
        except (OSError, subprocess.TimeoutExpired) as e:
            log.error("btmgmt %s failed: %s", args[0], e)

    @staticmethod
    def _advertising_active() -> bool:
        try:
            show = subprocess.run(["bluetoothctl", "show"], capture_output=True,
                                  text=True, stdin=subprocess.DEVNULL, timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            return False
        for line in show.stdout.splitlines():
            if "ActiveInstances" in line:
                return "0x00" not in line
        return False

    def _find_adapter(self, dbus, bus):
        om = dbus.Interface(bus.get_object(BLUEZ, "/"), OM_IFACE)
        for path, interfaces in om.GetManagedObjects().items():
            if GATT_MANAGER in interfaces and AD_MANAGER in interfaces:
                return path
        return None

    # --- data path ----------------------------------------------------------

    @property
    def connected(self) -> bool:
        return self._char is not None and self._char.notifying

    def _on_write(self, packet: bytes) -> None:
        self.on_bytes(packet)

    def send_midi(self, midi_bytes) -> None:
        """Notify one MIDI message to the subscribed central. Thread-safe:
        the actual D-Bus emission runs on the GLib loop."""
        if not self.connected:
            return
        ts = int((time.monotonic() - self._started_at) * 1000)
        packet = encode_message(midi_bytes, ts)

        def emit():
            try:
                self._char.send(packet)
            except Exception as e:
                log.error("BLE MIDI send failed: %s", e)
            return False  # one-shot idle callback

        self._glib.idle_add(emit)


def decode_incoming(packet: bytes) -> list[list[int]]:
    """Raw BLE packet -> MIDI messages; re-exported for the engine."""
    return decode_packet(packet)
