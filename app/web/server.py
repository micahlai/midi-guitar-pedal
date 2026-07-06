"""Configuration web server (Milestones 11-12).

Serves the single-page editor plus a JSON API on the port from
config["web"]. Edits swap whole dicts into the shared config (single
dict-item assignments under the GIL, so the render/logic threads see the
new values on their next config read), then persist with save_config().

API:
- GET  /                        editor page
- GET  /api/config              full config JSON
- GET  /api/status              live runtime state for the sidebar preview
- POST /api/slot/primary        {menu_id, button_num, action}
- POST /api/slot/secondary      {menu_id, button_num, hold_seconds, action}
- POST /api/slot/secondary/remove  {menu_id, button_num}
- POST /api/settings            subset of the editable global settings
"""

import json
import logging
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from config.loader import save_config
from config.model import ACTION_TYPES, get_menu
from state.manager import StateManager

log = logging.getLogger("controller.web")

STATIC_DIR = Path(__file__).parent / "static"

MAX_LABEL_LENGTH = 24
SECONDARY_ACTION_TYPES = ("effect_cc", "action_cc", "program_change")

_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def _midi7(value, name):
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 127:
        raise ValueError(f"{name} must be an integer 0-127")
    return value


def _channel(value):
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 16:
        raise ValueError("midi_channel must be an integer 1-16")
    return value


def _color(value, name):
    if not isinstance(value, str) or not _COLOR_RE.match(value):
        raise ValueError(f"{name} must be a #RRGGBB color")
    return value.upper()


def _bool(value, name):
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be true or false")
    return value


def _seconds(value, name, lo, hi):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not lo <= value <= hi:
        raise ValueError(f"{name} must be a number between {lo} and {hi}")
    return round(float(value), 2)


def validate_action(raw, allowed_types, allow_image: bool, pc_base: int = 0) -> dict:
    """Validate a full action dict from the client, returning a normalized
    copy with exactly the fields the config schema defines for its type."""
    if not isinstance(raw, dict):
        raise ValueError("action must be an object")
    action_type = raw.get("type")
    if action_type not in allowed_types:
        raise ValueError(f"action type must be one of {', '.join(allowed_types)}")
    label = raw.get("label", "")
    if not isinstance(label, str):
        raise ValueError("label must be a string")
    label = label.strip()[:MAX_LABEL_LENGTH]

    if action_type == "nothing":
        return {"type": "nothing", "label": label, "color": _color(raw.get("color", "#1A1A1A"), "color")}

    action = {
        "type": action_type,
        "midi_channel": _channel(raw.get("midi_channel")),
        "label": label,
    }
    if allow_image:
        image = raw.get("image_asset_id")
        if image is not None and not isinstance(image, str):
            raise ValueError("image_asset_id must be a string or null")
        action["image_asset_id"] = image

    if action_type == "effect_cc":
        action["cc_number"] = _midi7(raw.get("cc_number"), "cc_number")
        action["off_color"] = _color(raw.get("off_color"), "off_color")
        action["on_color"] = _color(raw.get("on_color"), "on_color")
    elif action_type == "action_cc":
        action["cc_number"] = _midi7(raw.get("cc_number"), "cc_number")
        action["default_color"] = _color(raw.get("default_color"), "default_color")
        action["pressed_color"] = _color(raw.get("pressed_color"), "pressed_color")
    elif action_type == "program_change":
        # Stored in the rig's numbering: wire value + program_display_base.
        number = raw.get("program_number")
        if (not isinstance(number, int) or isinstance(number, bool)
                or not pc_base <= number <= 127 + pc_base):
            raise ValueError(
                f"program_number must be an integer {pc_base}-{127 + pc_base}"
            )
        action["program_number"] = number
        action["inactive_color"] = _color(raw.get("inactive_color"), "inactive_color")
        action["active_color"] = _color(raw.get("active_color"), "active_color")
    elif action_type == "expression_pedal":
        action["cc_number"] = _midi7(raw.get("cc_number"), "cc_number")
        action["color"] = _color(raw.get("color"), "color")
        action["value_min"] = _midi7(raw.get("value_min"), "value_min")
        action["value_max"] = _midi7(raw.get("value_max"), "value_max")
        action["reverse"] = _bool(raw.get("reverse"), "reverse")
        action["has_home"] = _bool(raw.get("has_home"), "has_home")
        action["home_value"] = _midi7(raw.get("home_value"), "home_value")
    return action


def _get_slot_for_edit(state: StateManager, menu_id, button_num) -> dict:
    if not isinstance(menu_id, int) or get_menu(state.config, menu_id) is None:
        raise ValueError(f"unknown menu {menu_id!r}")
    if not isinstance(button_num, int) or not 1 <= button_num <= 9:
        raise ValueError(f"button must be 1-9, got {button_num!r}")
    menu = get_menu(state.config, menu_id)
    return menu.setdefault("slots", {}).setdefault(str(button_num), {})


def _clear_stale_expression_mode(state: StateManager, menu_id, button_num, role, action) -> None:
    """Deactivate the pot mode when the assignment it points at stops being
    an expression action — ExpressionLogic must never read expression fields
    off a foreign action type."""
    if state.expression_mode != (menu_id, button_num, role):
        return
    if action is None or action.get("type") != "expression_pedal":
        state.expression_mode = None


def set_primary(state: StateManager, menu_id, button_num, raw_action) -> dict:
    action = validate_action(raw_action, ACTION_TYPES, allow_image=True,
                             pc_base=state.config["midi"]["program_display_base"])
    slot = _get_slot_for_edit(state, menu_id, button_num)
    slot["primary"] = action
    _clear_stale_expression_mode(state, menu_id, button_num, "primary", action)
    return slot


def set_secondary(state: StateManager, menu_id, button_num, hold_seconds, raw_action) -> dict:
    action = validate_action(raw_action, SECONDARY_ACTION_TYPES, allow_image=False,
                             pc_base=state.config["midi"]["program_display_base"])
    hold = _seconds(hold_seconds, "hold_seconds", 0.2, 10.0)
    slot = _get_slot_for_edit(state, menu_id, button_num)
    if slot.get("primary") is None:
        raise ValueError("assign a primary action before adding a secondary")
    slot["secondary"] = {"enabled": True, "hold_seconds": hold, "action": action}
    _clear_stale_expression_mode(state, menu_id, button_num, "secondary", action)
    return slot


def remove_secondary(state: StateManager, menu_id, button_num) -> dict:
    slot = _get_slot_for_edit(state, menu_id, button_num)
    slot.pop("secondary", None)
    _clear_stale_expression_mode(state, menu_id, button_num, "secondary", None)
    return slot


def _iter_all_actions(config: dict):
    for menu in config["menus"]:
        for slot in menu.get("slots", {}).values():
            if slot.get("primary"):
                yield slot["primary"]
            secondary = slot.get("secondary")
            if secondary and secondary.get("action"):
                yield secondary["action"]


def apply_settings(config: dict, payload: dict) -> dict:
    """Validate and apply the editable global settings; returns what changed."""
    updates = {}
    if "program_display_base" in payload:
        base = payload["program_display_base"]
        if base not in (0, 1):
            raise ValueError("program_display_base must be 0 or 1")
        updates["program_display_base"] = (config["midi"], "program_display_base", base)
    if "shift_hold_seconds" in payload:
        updates["shift_hold_seconds"] = (
            config["buttons"], "shift_hold_seconds",
            _seconds(payload["shift_hold_seconds"], "shift_hold_seconds", 0.5, 10.0),
        )
    if "secondary_hold_default_seconds" in payload:
        updates["secondary_hold_default_seconds"] = (
            config["buttons"], "secondary_hold_default_seconds",
            _seconds(payload["secondary_hold_default_seconds"],
                     "secondary_hold_default_seconds", 0.2, 10.0),
        )
    if "expression_panel_width_ratio" in payload:
        value = payload["expression_panel_width_ratio"]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0.05 <= value <= 0.3:
            raise ValueError("expression_panel_width_ratio must be between 0.05 and 0.3")
        updates["expression_panel_width_ratio"] = (
            config["ui"], "expression_panel_width_ratio", round(float(value), 3),
        )
    if not updates:
        raise ValueError("no editable settings in request")
    old_base = config["midi"]["program_display_base"]
    applied = {}
    for name, (target, key, value) in updates.items():
        target[key] = value
        applied[name] = value
    # A base change re-numbers every stored program so the wire values (and
    # thus the patches actually targeted) stay the same.
    delta = config["midi"]["program_display_base"] - old_base
    if delta:
        for action in _iter_all_actions(config):
            if action.get("type") == "program_change":
                action["program_number"] += delta
    return applied


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
        elif self.path == "/api/status":
            state = self.app.state
            mode = state.expression_mode
            self._json(200, {
                "current_menu": state.current_menu,
                "current_program": state.current_program,
                "expression_detected": state.expression_detected,
                "expression_value": round(state.expression_value, 3),
                "expression_mode": list(mode) if mode else None,
            })
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        handler = {
            "/api/slot/primary": self.app.edit_primary,
            "/api/slot/secondary": self.app.edit_secondary,
            "/api/slot/secondary/remove": self.app.edit_remove_secondary,
            "/api/settings": self.app.edit_settings,
        }.get(self.path)
        if handler is None:
            self._json(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError("body must be a JSON object")
        except (ValueError, json.JSONDecodeError):
            self._json(400, {"error": "invalid JSON body"})
            return
        try:
            result = handler(payload)
        except ValueError as exc:
            self._json(400, {"error": str(exc)})
            return
        except Exception:
            log.exception("edit failed (%s)", self.path)
            self._json(500, {"error": "internal error"})
            return
        self._json(200, {"ok": True, **result})


class WebServer:
    def __init__(self, state: StateManager, save=save_config):
        self.state = state
        self.save = save
        self.port: int | None = None
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._edit_lock = threading.Lock()

    def _slot_edit(self, payload: dict, fn, *args) -> dict:
        menu_id, button_num = payload.get("menu_id"), payload.get("button_num")
        with self._edit_lock:
            slot = fn(self.state, menu_id, button_num, *args)
            self.save(self.state.config)
        log.info("web edit: menu %s B%s %s", menu_id, button_num, fn.__name__)
        return {"slot": slot}

    def edit_primary(self, payload: dict) -> dict:
        return self._slot_edit(payload, set_primary, payload.get("action"))

    def edit_secondary(self, payload: dict) -> dict:
        return self._slot_edit(
            payload, set_secondary, payload.get("hold_seconds"), payload.get("action")
        )

    def edit_remove_secondary(self, payload: dict) -> dict:
        return self._slot_edit(payload, remove_secondary)

    def edit_settings(self, payload: dict) -> dict:
        with self._edit_lock:
            applied = apply_settings(self.state.config, payload)
            self.save(self.state.config)
        log.info("web edit: settings %s", applied)
        return {"settings": applied}

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
