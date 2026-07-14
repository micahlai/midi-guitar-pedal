"""Captive-portal responder: joining the pedal's hotspot pops the editor open
by itself, the way a hotel/airport Wi-Fi login page does.

Every OS probes a known URL right after associating and decides from the
answer whether the network is "open" or behind a portal:

    macOS/iOS  http://captive.apple.com/hotspot-detect.html   expects "Success"
    Android    http://connectivitycheck.gstatic.com/generate_204   expects 204
    Windows    http://www.msftconnecttest.com/connecttest.txt  expects fixed text

Two things have to be true for the probe to reach us. DNS must resolve those
hostnames to the pedal — NetworkManager's shared mode runs dnsmasq, and
scripts/setup-captive-portal.sh drops an `address=/#/` wildcard into
/etc/NetworkManager/dnsmasq-shared.d/ (shared connections only, so the pedal's
own Wi-Fi client DNS is untouched). And the probe goes to port 80, not the
editor's 8080 — hence this second, tiny server.

Anything but the expected answer means "portal", so a blanket 302 to the
editor is enough; the OS then opens its captive-portal window on that URL.
Port 80 is privileged: the unit grants CAP_NET_BIND_SERVICE. If the bind
fails anyway the pedal simply has no auto-open — the editor is still reachable
by typing the address, so this must never be fatal.
"""

import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

log = logging.getLogger("controller.web.portal")

PORTAL_PORT = 80


class _PortalHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        # The address the client actually reached us on — 10.42.0.1 on the
        # hotspot, but never hardcoded: NM could hand out a different subnet.
        host = self.connection.getsockname()[0]
        target = f"http://{host}:{self.server.editor_port}/"
        body = (f'<html><head><meta http-equiv="refresh" content="0;url={target}">'
                f'</head><body><a href="{target}">Open the pedal editor</a>'
                f"</body></html>").encode()
        self.send_response(302)
        self.send_header("Location", target)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        # A cached redirect would keep firing on networks that are NOT the
        # pedal's, long after the laptop has moved on.
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.end_headers()
        self.wfile.write(body)

    do_POST = do_GET

    def log_message(self, format, *args):  # noqa: A002 - BaseHTTPRequestHandler API
        log.debug("portal: %s", format % args)


class PortalServer:
    """Redirects :80 to the editor. Harmless while the pedal is a Wi-Fi
    client — nothing hijacks DNS there, so no probe ever reaches it."""

    def __init__(self, state):
        self.state = state
        self._httpd = None
        self._thread = None

    def start(self, editor_port: int) -> None:
        try:
            self._httpd = ThreadingHTTPServer(("0.0.0.0", PORTAL_PORT),
                                              _PortalHandler)
        except OSError as exc:
            # Missing CAP_NET_BIND_SERVICE, or something else on :80. The
            # editor still works; only the auto-open is lost.
            log.warning("captive portal not available on port %d: %s",
                        PORTAL_PORT, exc)
            return
        self._httpd.editor_port = editor_port
        self._httpd.daemon_threads = True
        self._thread = threading.Thread(target=self._httpd.serve_forever,
                                        name="portal", daemon=True)
        self._thread.start()
        log.info("captive portal listening on port %d -> editor on %d",
                 PORTAL_PORT, editor_port)

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
        if self._thread:
            self._thread.join(timeout=2)
