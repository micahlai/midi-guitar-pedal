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
            self.on_disconnect = lambda: None  # set by BleMidiServer
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
            self.on_disconnect()

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
        self._dbus = None
        self._bus = None
        self._adapter_path = None
        self._app_path = None
        self._ad_path = None
        self._gatt = None
        self._ads = None

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
            self._dbus = dbus
            self._bus = bus
            self._adapter_path = adapter_path
            # A previous run may have died without stop() — SIGKILL, or the
            # power yanked mid-set. Its btmgmt advertising instance lives in
            # the kernel and its central may still be linked, both outliving
            # the process that owned the (now gone) GATT app. Clear both before
            # we register, or a host connects to the leftover peripheral and
            # finds no MIDI service.
            self._disconnect_centrals()
            self._btmgmt("rm-adv", "1")

            adapter_props = dbus.Interface(bus.get_object(BLUEZ, adapter_path), PROPS_IFACE)
            adapter_props.Set(ADAPTER, "Powered", dbus.Boolean(True))
            adapter_props.Set(ADAPTER, "Alias", dbus.String(self.device_name))
            # Advertising is not enough: a central that tries to bond against a
            # non-pairable adapter is refused, so the pedal SHOWS UP in the
            # host's Bluetooth list and then fails to connect. A fresh Pi image
            # comes up Pairable=no. This is independent of the settings menu's
            # "Pairing mode" row, which drives BR/EDR discoverability.
            adapter_props.Set(ADAPTER, "Pairable", dbus.Boolean(True))

            App, Service, Char, Ad = _build_classes(dbus, dbus.service)
            service = Service(bus)
            self._char = Char(bus, service, self._on_write)
            self._char.on_disconnect = self._on_central_disconnect
            service.characteristic = self._char
            app = App(bus, service)
            ad = Ad(bus, self.device_name)

            self._app_path = app.path
            self._ad_path = ad.path
            self._gatt = dbus.Interface(bus.get_object(BLUEZ, adapter_path), GATT_MANAGER)
            self._ads = dbus.Interface(bus.get_object(BLUEZ, adapter_path), AD_MANAGER)

            def gatt_registered():
                # Advertise only once the GATT app is actually served. A pedal
                # that advertises the MIDI service UUID with no MIDI service
                # behind it is what wedges CoreMIDI on macOS ("the MIDI server
                # can't be opened") — the host connects, finds nothing, and
                # keeps a broken driver object around.
                log.info("BLE MIDI GATT service registered")
                self._ads.RegisterAdvertisement(
                    ad.path, {},
                    reply_handler=lambda: log.info(
                        "BLE MIDI advertising as %r", self.device_name),
                    error_handler=self._advertising_failed)

            self._gatt.RegisterApplication(
                app.path, {},
                reply_handler=gatt_registered,
                error_handler=lambda e: log.error("GATT registration failed: %s", e))
        except Exception as e:
            log.error("BLE MIDI setup failed: %s", e)
            return False

        self._loop = GLib.MainLoop()
        self._thread = threading.Thread(target=self._loop.run, name="ble-midi", daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        """Tear the peripheral down in the order a host expects.

        macOS keeps a CoreMIDI driver object alive for a connected BLE-MIDI
        peripheral. Exiting without this teardown leaves the Mac's link to die
        by supervision timeout, and — worse — the btmgmt advertising instance
        lives in the kernel, not in this process, so it survives a service
        restart and keeps the pedal visible with the MIDI service UUID while
        the GATT app is gone. Connecting to that half-dead peripheral is what
        makes MIDIServer fail to start ("the MIDI server can't be opened"),
        and it stays broken until the Mac is rebooted. So: stop advertising,
        drop the central, unregister the app, then quit the loop.
        """
        self._unregister_advertisement()
        if self._legacy_instance is not None:
            self._btmgmt("rm-adv", str(self._legacy_instance))
            self._legacy_instance = None
        self._disconnect_centrals()
        self._unregister_application()
        if self._loop is not None:
            self._loop.quit()
            self._loop = None
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        self._char = None
        self._gatt = self._ads = self._bus = None

    def _unregister_advertisement(self) -> None:
        if self._ads is None or self._ad_path is None:
            return
        try:
            self._ads.UnregisterAdvertisement(self._ad_path)
            log.info("BLE MIDI advertisement unregistered")
        except Exception as e:  # already gone, bluetoothd restarted, ...
            log.warning("unregistering BLE advertisement failed: %s", e)
        self._ad_path = None

    def _unregister_application(self) -> None:
        if self._gatt is None or self._app_path is None:
            return
        try:
            self._gatt.UnregisterApplication(self._app_path)
            log.info("BLE MIDI GATT service unregistered")
        except Exception as e:
            log.warning("unregistering BLE GATT app failed: %s", e)
        self._app_path = None

    def _disconnect_centrals(self) -> None:
        """Disconnect every central on our adapter, so the host tears its side
        down cleanly instead of waiting out the supervision timeout."""
        if self._bus is None or self._dbus is None:
            return
        dbus = self._dbus
        try:
            om = dbus.Interface(self._bus.get_object(BLUEZ, "/"), OM_IFACE)
            objects = om.GetManagedObjects()
        except Exception as e:
            log.warning("could not enumerate BLE devices: %s", e)
            return
        for path, interfaces in objects.items():
            device = interfaces.get("org.bluez.Device1")
            if not device or not device.get("Connected"):
                continue
            if not str(path).startswith(str(self._adapter_path) + "/"):
                continue
            try:
                dbus.Interface(self._bus.get_object(BLUEZ, path),
                               "org.bluez.Device1").Disconnect()
                log.info("disconnected BLE central %s", path)
            except Exception as e:
                log.warning("disconnecting %s failed: %s", path, e)

    def _on_central_disconnect(self) -> None:
        """A connection on the btmgmt (legacy) path consumes the advertising
        instance — bluetoothd re-arms only its own D-Bus ads. Re-add the
        instance after the central goes away so the pedal reappears in scans
        (Milestone 16 reconnect handling)."""
        if self._legacy_instance is None:
            return
        log.info("BLE central disconnected; re-arming legacy advertising")
        threading.Thread(target=self._legacy_advertise, name="ble-readv",
                         daemon=True).start()

    def _advertising_failed(self, error) -> None:
        """bluetoothd 5.82 registers ads with the kernel's EXTENDED
        advertising MGMT commands, which kernel 6.18 rejects (Invalid
        Parameters) on the Zero 2 W's legacy-only radio. The legacy
        `btmgmt add-adv` path works, so fall back to it: a connectable,
        general-discoverable instance carrying the MIDI service UUID and the
        adapter name in the scan response (-n; without it macOS lists the
        pedal namelessly or not at all). Connections still land on the
        bluetoothd-served GATT app.

        Runs on a worker thread: it sleeps waiting for adapter power-up
        (at boot the instance would otherwise be installed before the radio
        is on and never start transmitting), and must not block GLib."""
        log.warning("D-Bus advertising failed (%s); using btmgmt fallback", error)
        threading.Thread(target=self._legacy_advertise, name="ble-adv", daemon=True).start()

    def _legacy_advertise(self) -> None:
        for _ in range(10):
            if self._adapter_powered():
                break
            time.sleep(2)
        else:
            log.error("adapter never powered on; BLE advertising not started")
            return
        # The -c below marks the ADVERTISING INSTANCE connectable, but the
        # ADAPTER has its own `connectable` setting and a fresh Pi image comes
        # up with it OFF. The pedal then advertises — the host lists it — and
        # the controller refuses the incoming connection: "shows up in the
        # Bluetooth list, won't connect". Nothing logs an error either side.
        self._btmgmt("connectable", "on")
        self._btmgmt("rm-adv", "1")
        out = self._btmgmt("add-adv", "-c", "-g", "-s", self._scan_rsp_hex(),
                           "-u", MIDI_SERVICE_UUID, "1")
        if "Instance added" not in out:
            log.error("btmgmt add-adv did not confirm (%r); BLE advertising "
                      "is likely NOT running", out.strip())
            return
        self._legacy_instance = 1
        # NOTE: bluetoothd's ActiveInstances does NOT track instances added
        # via btmgmt (always shows 0) — the "Instance added" confirmation
        # above is the real success signal.
        log.info("BLE MIDI advertising via btmgmt (legacy) as %r", self.device_name)

    def _scan_rsp_hex(self) -> str:
        """Scan response AD structure carrying the device name — btmgmt's -n
        flag doesn't actually emit one, so build it by hand. Type 0x09 =
        Complete Local Name, 0x08 = Shortened (when truncated to the 31-byte
        scan response budget)."""
        name = self.device_name.encode()[:29]
        ad_type = 0x09 if name == self.device_name.encode() else 0x08
        return bytes([len(name) + 1, ad_type, *name]).hex()

    @staticmethod
    def _btmgmt(*args) -> str:
        """Run a btmgmt command and return its output. btmgmt issues NOTHING
        without a controlling terminal — it opens the MGMT socket and just
        waits (confirmed via btmon: socket opens, zero commands sent), so the
        old plain-subprocess invocation silently no-opped. `script` provides
        a pseudo-TTY, which also makes btmgmt print its confirmation and exit
        promptly; `timeout` still guards the hang case. Args must stay
        shell-safe (script -c goes through sh)."""
        command = " ".join(("btmgmt",) + args)
        try:
            result = subprocess.run(
                ["sudo", "-n", "timeout", "5", "script", "-qec", command, "/dev/null"],
                capture_output=True, text=True, stdin=subprocess.DEVNULL,
                timeout=15)
            log.debug("btmgmt %s: %s", args[0], result.stdout.strip())
            return result.stdout
        except (OSError, subprocess.TimeoutExpired) as e:
            log.error("btmgmt %s failed: %s", args[0], e)
            return ""

    @staticmethod
    def _adapter_powered() -> bool:
        try:
            show = subprocess.run(["bluetoothctl", "show"], capture_output=True,
                                  text=True, stdin=subprocess.DEVNULL, timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            return False
        return any("Powered: yes" in line for line in show.stdout.splitlines())

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
