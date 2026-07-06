"""Configuration web server (Milestone 11).

Serves a single-page slot editor plus a small JSON API on the port from
config["web"]. Edits replace one slot's "primary" dict in place — a single
dict-item assignment under the GIL, so the render/logic threads simply see
the new action on their next config read — then persist with save_config().
"""

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from config.loader import save_config
from config.model import ACTION_TYPES, get_menu
from state.manager import StateManager

log = logging.getLogger("controller.web")

STATIC_DIR = Path(__file__).parent / "static"

MAX_LABEL_LENGTH = 24


def make_primary_action(action_type: str, label: str, midi_channel: int) -> dict:
    """A fresh action dict of the given type with sensible defaults, matching
    the shapes in config/defaults.py."""
    if action_type == "nothing":
        return {"type": "nothing", "label": label, "color": "#1A1A1A"}
    action = {
        "type": action_type,
        "midi_channel": midi_channel,
        "label": label,
        "image_asset_id": None,
    }
    if action_type == "effect_cc":
        action.update(cc_number=20, off_color="#303030", on_color="#00FF66")
    elif action_type == "action_cc":
        action.update(cc_number=20, default_color="#303030", pressed_color="#FF6600")
    elif action_type == "program_change":
        action.update(program_number=0, inactive_color="#303030", active_color="#3399FF")
    elif action_type == "expression_pedal":
        action.update(
            cc_number=7, color="#FFCC00", value_min=0, value_max=127,
            reverse=False, has_home=False, home_value=0,
        )
    return action


def set_primary_action(state: StateManager, menu_id, button_num, action_type, label) -> dict:
    """Validate and apply a primary-action edit; returns the updated slot.

    Same-type edits only touch the label so tuned fields (CC numbers,
    colors, ...) survive; a type change swaps in a fresh template.
    """
    config = state.config
    if not isinstance(menu_id, int) or get_menu(config, menu_id) is None:
        raise ValueError(f"unknown menu {menu_id!r}")
    if not isinstance(button_num, int) or not 1 <= button_num <= 9:
        raise ValueError(f"button must be 1-9, got {button_num!r}")
    if action_type not in ACTION_TYPES:
        raise ValueError(f"unknown action type {action_type!r}")
    if not isinstance(label, str):
        raise ValueError("label must be a string")
    label = label.strip()[:MAX_LABEL_LENGTH]

    menu = get_menu(config, menu_id)
    slot = menu.setdefault("slots", {}).setdefault(str(button_num), {})
    primary = slot.get("primary")
    if primary is not None and primary.get("type") == action_type:
        primary["label"] = label
    else:
        slot["primary"] = make_primary_action(
            action_type, label, config["midi"]["default_channel"]
        )
        # If this slot's primary was the active pot mode and is no longer an
        # expression action, deactivate it so ExpressionLogic doesn't read
        # expression fields off a foreign action type.
        mode = state.expression_mode
        if (mode is not None and mode == (menu_id, button_num, "primary")
                and action_type != "expression_pedal"):
            state.expression_mode = None
    return slot


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        log.debug("http " + fmt, *args)

    @property
    def app(self) -> "WebServer":
        return self.server.app

    def _respond(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, payload) -> None:
        self._respond(status, json.dumps(payload).encode(), "application/json")

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._respond(200, (STATIC_DIR / "index.html").read_bytes(),
                          "text/html; charset=utf-8")
        elif self.path == "/api/config":
            self._json(200, self.app.state.config)
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/api/slot":
            self._json(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(length))
        except (ValueError, json.JSONDecodeError):
            self._json(400, {"error": "invalid JSON body"})
            return
        try:
            slot = self.app.update_primary(payload)
        except ValueError as exc:
            self._json(400, {"error": str(exc)})
            return
        except Exception:
            log.exception("slot update failed")
            self._json(500, {"error": "internal error"})
            return
        self._json(200, {"ok": True, "slot": slot})


class WebServer:
    def __init__(self, state: StateManager, save=save_config):
        self.state = state
        self.save = save
        self.port: int | None = None
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._edit_lock = threading.Lock()

    def update_primary(self, payload: dict) -> dict:
        if not isinstance(payload, dict):
            raise ValueError("body must be a JSON object")
        with self._edit_lock:
            slot = set_primary_action(
                self.state,
                payload.get("menu_id"),
                payload.get("button_num"),
                payload.get("type"),
                payload.get("label", ""),
            )
            self.save(self.state.config)
        log.info(
            "web edit: menu %s button %s -> %s %r",
            payload.get("menu_id"), payload.get("button_num"),
            payload.get("type"), payload.get("label", ""),
        )
        return slot

    def start(self) -> None:
        web_cfg = self.state.config.get("web", {})
        if not web_cfg.get("enabled", True):
            log.info("web server disabled in config")
            return
        port = web_cfg.get("port", 8080)
        try:
            self._httpd = ThreadingHTTPServer(("0.0.0.0", port), _Handler)
        except OSError as exc:
            log.error("web server failed to bind port %d: %s", port, exc)
            return
        self._httpd.app = self
        self._httpd.daemon_threads = True
        self.port = self._httpd.server_address[1]
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, name="web", daemon=True
        )
        self._thread.start()
        log.info("web server listening on port %d", self.port)

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        log.info("web server stopped")
