"""Access-point fallback: if the pedal boots somewhere with no known Wi-Fi,
it hosts its own network so the web editor is still reachable from a laptop.

The check is one-shot, FALLBACK_SECONDS after boot — long enough for
NetworkManager to have tried every saved profile, so a slow-associating home
network is never pre-empted by the AP. Nothing here reconnects on its own
afterwards: once the AP is up it stays up until the user turns it off from
the settings menu (or reboots, since the AP profile is autoconnect=no).

The radio cannot be client and AP simultaneously, so raising the AP means
leaving whatever network the pedal was on. That only happens when it is on
none.
"""

import logging
import threading

from hardware import sysinfo

log = logging.getLogger("controller.logic.hotspot")


class HotspotLogic:
    def __init__(self, state, sysinfo_module=sysinfo):
        self.state = state
        self.sysinfo = sysinfo_module
        self._boot: float | None = None
        self._checking = False
        self._checked = False

    def _settings(self) -> dict:
        return self.state.config.get("hotspot", {})

    def tick(self, now: float) -> None:
        """Called from the main loop; the probe itself runs on a worker."""
        if self._checked or self._checking:
            return
        settings = self._settings()
        if not settings.get("auto_fallback", True):
            return
        if self._boot is None:
            self._boot = now
            return
        if now - self._boot < settings.get("fallback_seconds", 45):
            return
        self._checked = True  # one shot, however it turns out
        self._checking = True
        threading.Thread(target=self._fallback, daemon=True,
                         name="hotspot-fallback").start()

    def _fallback(self) -> None:
        """Worker thread: host the AP only if we ended up on no network."""
        try:
            if self.sysinfo.wifi_connected():
                log.info("wifi up — no hotspot fallback needed")
                return
            if self.sysinfo.ap_active():
                return
            settings = self._settings()
            ssid = settings.get("ssid") or "GuitarPedal"
            password = settings.get("password") or "pedalsetup"
            log.warning("no wifi after boot — starting hotspot %s", ssid)
            ok, message = self.sysinfo.ap_start(ssid, password)
            if not ok:
                log.error("hotspot fallback failed: %s", message)
        except Exception:
            log.exception("hotspot fallback failed")
        finally:
            self._checking = False
