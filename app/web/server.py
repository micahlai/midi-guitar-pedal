"""Configuration web server (Milestones 11-12).

Serves the single-page editor plus a JSON API on the port from
config["web"]. Edits swap whole dicts into the shared config (single
dict-item assignments under the GIL, so the render/logic threads see the
new values on their next config read), then persist with save_config().

API:
- GET  /                        editor page
- GET  /api/config              full config JSON
- GET  /api/status              live runtime state for the sidebar preview
- GET  /api/presets             saved preset names
- GET  /api/preset/export?name= preset file download (no name: live config)
- POST /api/slot/primary        {menu_id, button_num, action}
- POST /api/slot/secondary      {menu_id, button_num, hold_seconds, action}
- POST /api/slot/secondary/remove  {menu_id, button_num}
- POST /api/settings            subset of the editable global settings
- POST /api/menu                {menu_id, name}
- POST /api/menu/swap           {menu_id, other_id}  swap two menus' contents
- POST /api/palette             {colors: [10 x #RRGGBB]}
- POST /api/preset/save|load|delete  {name}
- POST /api/preset/new          {name, blank?} (blank: no button assignments)
- POST /api/preset/import       {name, config}
- POST /api/undo, /api/redo     -> {config}

Every mutating endpoint snapshots the config for undo; history is in-memory
only (a restart clears it, per the Milestone 12.5 spec).
"""

import copy
import json
import logging
import re
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from config import presets
from config.defaults import copy_device_settings, strip_device_settings
from config.loader import save_config
from logic import header
from web import images
from config.model import ACTION_TYPES, PALETTE_SIZE, get_menu, iter_expression_actions
from logic.expression import ACTION_DEFAULTS, SELECT_MODES
from state.manager import StateManager

log = logging.getLogger("controller.web")

STATIC_DIR = Path(__file__).parent / "static"

MAX_LABEL_LENGTH = 24
MAX_MENU_NAME_LENGTH = 24
UNDO_LIMIT = 100
SECONDARY_ACTION_TYPES = ("effect_cc", "action_cc", "program_change", "expression_pedal")

_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
_PALETTE_REF_RE = re.compile(rf"^palette:[0-{PALETTE_SIZE - 1}]$")


def _midi7(value, name):
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 127:
        raise ValueError(f"{name} must be an integer 0-127")
    return value


def _channel(value):
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 16:
        raise ValueError("midi_channel must be an integer 1-16")
    return value


def _color(value, name, allow_palette=True):
    """Action colors are literal #RRGGBB or a "palette:N" reference into the
    shared ui.color_palette (linked colors, Milestone 12.5)."""
    if allow_palette and isinstance(value, str) and _PALETTE_REF_RE.match(value):
        return value
    if not isinstance(value, str) or not _COLOR_RE.match(value):
        raise ValueError(f"{name} must be a #RRGGBB color or palette:0-{PALETTE_SIZE - 1}")
    return value.upper()


def _bool(value, name):
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be true or false")
    return value


def _seconds(value, name, lo, hi):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not lo <= value <= hi:
        raise ValueError(f"{name} must be a number between {lo} and {hi}")
    return round(float(value), 2)


def _int(value, name, lo, hi):
    if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
        raise ValueError(f"{name} must be an integer {lo}-{hi}")
    return value


def _string(value, name, max_len):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()[:max_len]


def _header_slots(value):
    """The header's 5 positions (logic/header.py). Enforced here, not just in
    the browser: one item per position, one position per item, so an API caller
    cannot write a config the on-device menu could never produce."""
    if not isinstance(value, list) or len(value) != header.SLOT_COUNT:
        raise ValueError(f"header must be a list of {header.SLOT_COUNT} items")
    seen = set()
    slots = []
    for item in value:
        if item is None:
            slots.append(None)
            continue
        if item not in header.ITEM_KEYS:
            raise ValueError(f"unknown header item: {item!r}")
        if item in seen:
            raise ValueError(f"header item appears twice: {item!r}")
        seen.add(item)
        slots.append(item)
    return slots


def validate_action(raw, allowed_types, secondary: bool, pc_base: int = 0) -> dict:
    """Validate a full action dict from the client, returning a normalized
    copy with exactly the fields the config schema defines for its type.

    Color model: primaries carry off_color + on_color; secondaries carry
    on_color only (and never an image).
    """
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
        "on_color": _color(raw.get("on_color"), "on_color"),
    }
    if not secondary:
        action["off_color"] = _color(raw.get("off_color"), "off_color")
        image = raw.get("image_asset_id")
        if image is not None:
            image = images.validate_asset_id(image)
        action["image_asset_id"] = image

    if action_type in ("effect_cc", "action_cc"):
        action["cc_number"] = _midi7(raw.get("cc_number"), "cc_number")
        if action_type == "action_cc" and secondary:
            # How long the on_color shows after the hold fires the secondary
            # (there is no "held" period to display — the fire IS the hold).
            action["color_duration"] = _seconds(
                raw.get("color_duration", 1.0), "color_duration", 0.1, 10.0)
    elif action_type == "program_change":
        # Stored in the rig's numbering: wire value + program_display_base.
        number = raw.get("program_number")
        if (not isinstance(number, int) or isinstance(number, bool)
                or not pc_base <= number <= 127 + pc_base):
            raise ValueError(
                f"program_number must be an integer {pc_base}-{127 + pc_base}"
            )
        action["program_number"] = number
    elif action_type == "expression_pedal":
        action["cc_number"] = _midi7(raw.get("cc_number"), "cc_number")
        action["value_min"] = _midi7(raw.get("value_min"), "value_min")
        action["value_max"] = _midi7(raw.get("value_max"), "value_max")
        action["reverse"] = _bool(raw.get("reverse"), "reverse")
        action["has_home"] = _bool(raw.get("has_home"), "has_home")
        action["home_value"] = _midi7(raw.get("home_value"), "home_value")
        # How this effect meets the pedal when selected, and how fast it walks
        # home when left — per-effect, so they travel with the preset.
        select_mode = raw.get("select_mode", ACTION_DEFAULTS["select_mode"])
        if select_mode not in SELECT_MODES:
            raise ValueError("select_mode must be one of %s" % ", ".join(SELECT_MODES))
        action["select_mode"] = select_mode
        for name, lo, hi in (
            ("return_alpha", 0.01, 1.0),
            ("return_stop_threshold", 0.0, 5.0),
            ("select_alpha", 0.01, 1.0),
            ("select_stop_threshold", 0.0, 5.0),
        ):
            action[name] = _seconds(raw.get(name, ACTION_DEFAULTS[name]), name, lo, hi)
        # The pot's fallback assignment when no expression button is selected;
        # at most one across the whole config (enforced on save).
        action["is_default"] = _bool(raw.get("is_default", False), "is_default")
    return action


def _enforce_single_default_expression(config: dict, menu_id, button_num, role) -> None:
    """Clear is_default on every OTHER expression assignment so only one
    default (one CC number) exists config-wide."""
    for mid, num, r, action in iter_expression_actions(config):
        if (mid, num, r) != (menu_id, button_num, role) and action.get("is_default"):
            action["is_default"] = False


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
    action = validate_action(raw_action, ACTION_TYPES, secondary=False,
                             pc_base=state.config["midi"]["program_display_base"])
    slot = _get_slot_for_edit(state, menu_id, button_num)
    slot["primary"] = action
    if action.get("is_default"):
        _enforce_single_default_expression(state.config, menu_id, button_num, "primary")
    _clear_stale_expression_mode(state, menu_id, button_num, "primary", action)
    return slot


def set_secondary(state: StateManager, menu_id, button_num, hold_seconds, raw_action) -> dict:
    action = validate_action(raw_action, SECONDARY_ACTION_TYPES, secondary=True,
                             pc_base=state.config["midi"]["program_display_base"])
    hold = _seconds(hold_seconds, "hold_seconds", 0.2, 10.0)
    slot = _get_slot_for_edit(state, menu_id, button_num)
    if slot.get("primary") is None:
        raise ValueError("assign a primary action before adding a secondary")
    slot["secondary"] = {"enabled": True, "hold_seconds": hold, "action": action}
    if action.get("is_default"):
        _enforce_single_default_expression(state.config, menu_id, button_num, "secondary")
    _clear_stale_expression_mode(state, menu_id, button_num, "secondary", action)
    return slot


def remove_secondary(state: StateManager, menu_id, button_num) -> dict:
    slot = _get_slot_for_edit(state, menu_id, button_num)
    slot.pop("secondary", None)
    _clear_stale_expression_mode(state, menu_id, button_num, "secondary", None)
    return slot


def set_menu_name(config: dict, menu_id, name) -> dict:
    if not isinstance(menu_id, int) or get_menu(config, menu_id) is None:
        raise ValueError(f"unknown menu {menu_id!r}")
    if not isinstance(name, str):
        raise ValueError("name must be a string")
    menu = get_menu(config, menu_id)
    menu["name"] = name.strip()[:MAX_MENU_NAME_LENGTH] or f"Menu {menu_id}"
    return {"menu_id": menu_id, "name": menu["name"]}


def swap_menus(state: StateManager, menu_id, other_id) -> dict:
    """Swap the full contents (name + button assignments) of two menus,
    keeping each menu's id (physical position). Nothing about the wire
    behavior changes — the same actions just live under a different menu."""
    config = state.config
    for mid in (menu_id, other_id):
        if not isinstance(mid, int) or get_menu(config, mid) is None:
            raise ValueError(f"unknown menu {mid!r}")
    if menu_id == other_id:
        raise ValueError("cannot swap a menu with itself")
    a, b = get_menu(config, menu_id), get_menu(config, other_id)
    a["name"], b["name"] = b["name"], a["name"]
    a["slots"], b["slots"] = b.get("slots", {}), a.get("slots", {})
    # The active pot mode is tied to (menu, button, role); its slot just moved,
    # so deactivate it rather than let ExpressionLogic read a foreign slot.
    if state.expression_mode and state.expression_mode[0] in (menu_id, other_id):
        state.expression_mode = None
    return {"menu_id": menu_id, "other_id": other_id,
            "menus": [{"id": m["id"], "name": m["name"]} for m in config["menus"]]}


MAX_PALETTE_LABEL_LENGTH = 20


def set_palette(config: dict, colors=None, labels=None) -> dict:
    """Update the palette colors and/or their labels; returns both lists.
    Both live in the config, so presets snapshot them automatically."""
    if colors is None and labels is None:
        raise ValueError("provide colors and/or labels")
    if colors is not None:
        if not isinstance(colors, list) or len(colors) != PALETTE_SIZE:
            raise ValueError(f"colors must be a list of {PALETTE_SIZE} #RRGGBB values")
        config["ui"]["color_palette"] = [
            _color(c, f"colors[{i}]", allow_palette=False) for i, c in enumerate(colors)
        ]
    if labels is not None:
        if (not isinstance(labels, list) or len(labels) != PALETTE_SIZE
                or not all(isinstance(l, str) for l in labels)):
            raise ValueError(f"labels must be a list of {PALETTE_SIZE} strings")
        config["ui"]["color_palette_labels"] = [
            l.strip()[:MAX_PALETTE_LABEL_LENGTH] for l in labels
        ]
    return {"colors": config["ui"]["color_palette"],
            "labels": config["ui"]["color_palette_labels"]}


def install_config(state: StateManager, new_config: dict) -> None:
    """Kept as the web module's seam; the real logic lives on StateManager
    so the on-device settings menu can swap presets too."""
    state.install_config(new_config)


def _iter_all_actions(config: dict):
    for menu in config["menus"]:
        for slot in menu.get("slots", {}).values():
            if slot.get("primary"):
                yield slot["primary"]
            secondary = slot.get("secondary")
            if secondary and secondary.get("action"):
                yield secondary["action"]


def clear_image_references(config: dict, asset_id: str) -> int:
    cleared = 0
    for action in _iter_all_actions(config):
        if action.get("image_asset_id") == asset_id:
            action["image_asset_id"] = None
            cleared += 1
    return cleared


def apply_settings(config: dict, payload: dict) -> dict:
    """Validate and apply the editable global settings; returns what changed.

    Covers both scopes shown on the web Settings tab: preset-scoped values
    (saved into presets) and device-scoped values (see
    config.defaults.DEVICE_SETTING_PATHS — presets never touch them).
    """
    updates = {}

    # --- preset-scoped ------------------------------------------------------
    if "program_display_base" in payload:
        base = payload["program_display_base"]
        if base not in (0, 1):
            raise ValueError("program_display_base must be 0 or 1")
        updates["program_display_base"] = (config["midi"], "program_display_base", base)
    if "default_channel" in payload:
        updates["default_channel"] = (
            config["midi"], "default_channel", _channel(payload["default_channel"]),
        )
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
    for theme_key in ("background", "panel_background", "text", "disabled",
                      "expression_pedal"):
        name = f"theme_{theme_key}"
        if name in payload:
            updates[name] = (
                config["ui"]["theme"], theme_key,
                _color(payload[name], name, allow_palette=False),
            )
    if "preset_name" in payload:
        updates["preset_name"] = (
            config, "preset_name", presets.validate_preset_name(payload["preset_name"]),
        )

    # --- device-scoped ------------------------------------------------------
    if "device_name" in payload:
        updates["device_name"] = (
            config["device"], "name", _string(payload["device_name"], "device_name", 32),
        )
    if "web_port" in payload:
        updates["web_port"] = (
            config["web"], "port", _int(payload["web_port"], "web_port", 1024, 65535),
        )
    for transport in ("usb_enabled", "ble_enabled"):
        if transport in payload:
            updates[transport] = (
                config["midi"], transport, _bool(payload[transport], transport),
            )
    for name, key, lo, hi in (
        ("debounce_ms", "debounce_ms", 5, 200),
        ("power_double_press_ms", "power_double_press_ms", 150, 2000),
    ):
        if name in payload:
            updates[name] = (config["buttons"], key, _int(payload[name], name, lo, hi))
    if "power_hold_seconds" in payload:
        updates["power_hold_seconds"] = (
            config["buttons"], "power_hold_seconds",
            _seconds(payload["power_hold_seconds"], "power_hold_seconds", 0.5, 10.0),
        )
    if "header" in payload:
        updates["header"] = (
            config["ui"], "header", _header_slots(payload["header"]),
        )
    for name in ("detect_enabled", "retain_pedal_value"):
        if name in payload:
            updates[name] = (config["expression"], name, _bool(payload[name], name))
    # select_mode and the return/select speeds are per-effect (parsed in
    # _action_from_payload), not device settings.
    for name, lo, hi in (
        ("send_deadband", 0, 16),
        ("poll_interval_ms", 5, 100),
        ("return_interval_ms", 10, 200),
    ):
        if name in payload:
            updates[name] = (config["expression"], name, _int(payload[name], name, lo, hi))

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
        path, _, query = self.path.partition("?")
        if path in ("/", "/index.html"):
            self._respond(200, (STATIC_DIR / "index.html").read_bytes(),
                          "text/html; charset=utf-8")
        elif path == "/api/config":
            self._json(200, self.app.state.config)
        elif path == "/api/presets":
            self._json(200, {"presets": presets.list_presets(),
                             "current": self.app.state.config.get("preset_name", "")})
        elif path == "/api/preset/export":
            name = urllib.parse.parse_qs(query).get("name", [None])[0]
            try:
                config = presets.load_preset(name) if name else self.app.state.config
            except ValueError as exc:
                self._json(400, {"error": str(exc)})
                return
            # Exports are preset files: no device-scoped settings.
            config = copy.deepcopy(config)
            strip_device_settings(config)
            body = json.dumps(config, indent=2).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header(
                "Content-Disposition",
                f'attachment; filename="{name or config.get("preset_name", "preset")}.json"',
            )
            self.end_headers()
            self.wfile.write(body)
        elif path == "/api/images":
            self._json(200, {"images": images.list_images()})
        elif path.startswith("/images/"):
            try:
                file = images.image_path(path[len("/images/"):].removesuffix(".png"))
            except ValueError:
                self._json(404, {"error": "not found"})
                return
            if not file.exists():
                self._json(404, {"error": "not found"})
                return
            self._respond(200, file.read_bytes(), "image/png")
        elif path == "/api/status":
            state = self.app.state
            mode = state.effective_expression_mode()
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
            "/api/menu": self.app.edit_menu,
            "/api/menu/swap": self.app.swap_menu,
            "/api/palette": self.app.edit_palette,
            "/api/preset/save": self.app.preset_save,
            "/api/preset/load": self.app.preset_load,
            "/api/preset/delete": self.app.preset_delete,
            "/api/preset/new": self.app.preset_new,
            "/api/preset/import": self.app.preset_import,
            "/api/image": self.app.image_upload,
            "/api/image/delete": self.app.image_delete,
            "/api/undo": self.app.undo,
            "/api/redo": self.app.redo,
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
        # Undo/redo history: full-config snapshots, in-memory only.
        self._undo: list[dict] = []
        self._redo: list[dict] = []

    def _mutate(self, fn) -> dict:
        """Run a config mutation under the edit lock: snapshot for undo,
        apply, persist. A failed mutation may leave partial changes in the
        live config, so restore the snapshot on any error."""
        with self._edit_lock:
            before = copy.deepcopy(self.state.config)
            try:
                result = fn()
            except Exception:
                install_config(self.state, before)
                raise
            self._undo.append(before)
            del self._undo[:-UNDO_LIMIT]
            self._redo.clear()
            self.state.config_version += 1
            self.save(self.state.config)
        return result

    def _slot_edit(self, payload: dict, fn, *args) -> dict:
        menu_id, button_num = payload.get("menu_id"), payload.get("button_num")
        result = self._mutate(lambda: {"slot": fn(self.state, menu_id, button_num, *args)})
        log.info("web edit: menu %s B%s %s", menu_id, button_num, fn.__name__)
        return result

    def edit_primary(self, payload: dict) -> dict:
        return self._slot_edit(payload, set_primary, payload.get("action"))

    def edit_secondary(self, payload: dict) -> dict:
        return self._slot_edit(
            payload, set_secondary, payload.get("hold_seconds"), payload.get("action")
        )

    def edit_remove_secondary(self, payload: dict) -> dict:
        return self._slot_edit(payload, remove_secondary)

    def edit_settings(self, payload: dict) -> dict:
        result = self._mutate(
            lambda: {"settings": apply_settings(self.state.config, payload)}
        )
        log.info("web edit: settings %s", result["settings"])
        return result

    def edit_menu(self, payload: dict) -> dict:
        result = self._mutate(lambda: {"menu": set_menu_name(
            self.state.config, payload.get("menu_id"), payload.get("name"))})
        log.info("web edit: menu name %s", result["menu"])
        return result

    def swap_menu(self, payload: dict) -> dict:
        result = self._mutate(lambda: {"swap": swap_menus(
            self.state, payload.get("menu_id"), payload.get("other_id"))})
        log.info("web edit: swapped menus %s <-> %s",
                 payload.get("menu_id"), payload.get("other_id"))
        return {"config": self.state.config, **result}

    def edit_palette(self, payload: dict) -> dict:
        result = self._mutate(lambda: {"palette": set_palette(
            self.state.config, payload.get("colors"), payload.get("labels"))})
        log.info("web edit: palette updated")
        return result

    # --- presets -------------------------------------------------------------

    def preset_save(self, payload: dict) -> dict:
        # Saving a preset file doesn't change the live config beyond its name.
        name = payload.get("name")
        result = self._mutate(lambda: self._do_preset_save(name))
        log.info("preset saved: %s", name)
        return result

    def _do_preset_save(self, name) -> dict:
        presets.save_preset(name, self.state.config)
        self.state.config["preset_name"] = presets.validate_preset_name(name)
        return {"presets": presets.list_presets()}

    def preset_load(self, payload: dict) -> dict:
        name = payload.get("name")
        result = self._mutate(
            lambda: self._install(presets.load_preset(name))
        )
        log.info("preset loaded: %s", name)
        return result

    def preset_new(self, payload: dict) -> dict:
        name = payload.get("name")
        blank = payload.get("blank", False)
        if not isinstance(blank, bool):
            raise ValueError("blank must be true or false")
        result = self._mutate(
            lambda: self._install(presets.new_preset_config(name, blank=blank))
        )
        log.info("new preset started: %s%s", name, " (blank)" if blank else "")
        return result

    def preset_import(self, payload: dict) -> dict:
        name = payload.get("name")
        with self._edit_lock:  # writes a preset file, not the live config
            presets.import_preset(name, payload.get("config"))
        log.info("preset imported: %s", name)
        return {"presets": presets.list_presets()}

    def preset_delete(self, payload: dict) -> dict:
        name = payload.get("name")
        with self._edit_lock:
            presets.delete_preset(name)
        log.info("preset deleted: %s", name)
        return {"presets": presets.list_presets()}

    # --- images --------------------------------------------------------------

    def image_upload(self, payload: dict) -> dict:
        image = images.save_image(payload.get("name"), payload.get("data"))
        log.info("image uploaded: %s", image["id"])
        return {"image": image, "images": images.list_images()}

    def image_delete(self, payload: dict) -> dict:
        asset_id = images.validate_asset_id(payload.get("id"))
        # Clear config references first (undoable), then remove the file
        # (file deletion itself is not undoable).
        cleared = self._mutate(
            lambda: {"cleared": clear_image_references(self.state.config, asset_id)}
        )
        images.delete_image(asset_id)
        log.info("image deleted: %s (%d references cleared)", asset_id, cleared["cleared"])
        return {"images": images.list_images(), **cleared}

    def _install(self, new_config: dict) -> dict:
        # Presets never carry device-scoped settings; keep this device's.
        copy_device_settings(self.state.config, new_config)
        install_config(self.state, new_config)
        return {"config": self.state.config}

    # --- undo/redo -----------------------------------------------------------

    def undo(self, payload: dict) -> dict:
        with self._edit_lock:
            if not self._undo:
                raise ValueError("nothing to undo")
            self._redo.append(copy.deepcopy(self.state.config))
            install_config(self.state, self._undo.pop())
            self.save(self.state.config)
        log.info("web edit: undo (%d left)", len(self._undo))
        return {"config": self.state.config}

    def redo(self, payload: dict) -> dict:
        with self._edit_lock:
            if not self._redo:
                raise ValueError("nothing to redo")
            self._undo.append(copy.deepcopy(self.state.config))
            install_config(self.state, self._redo.pop())
            self.save(self.state.config)
        log.info("web edit: redo (%d left)", len(self._redo))
        return {"config": self.state.config}

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
