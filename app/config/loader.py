"""Load and save the controller configuration JSON.

The config lives outside the app directory so deploys never clobber it:
    /opt/midi-controller/config/config.json
A missing file is created from defaults. Version migrations land in a later
milestone; for now a mismatched version is rejected loudly.
"""

import json
import logging
import os
from pathlib import Path

from config.defaults import CONFIG_VERSION, default_config

log = logging.getLogger("controller.config")

CONFIG_DIR = Path(os.environ.get("CONTROLLER_CONFIG_DIR", "/opt/midi-controller/config"))
CONFIG_PATH = CONFIG_DIR / "config.json"


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        log.info("no config at %s, writing defaults", CONFIG_PATH)
        config = default_config()
        save_config(config)
        return config

    with CONFIG_PATH.open() as f:
        config = json.load(f)

    if prepare_config(config):
        log.info("config migrated to the current schema")
        save_config(config)
    return config


def prepare_config(config: dict) -> bool:
    """Validate the version and bring a raw config dict up to the current
    schema (back-fill missing keys, migrate old color fields). Used for the
    live config and for loaded/imported presets. Returns True if the color
    migration changed anything."""
    if not isinstance(config, dict) or config.get("version") != CONFIG_VERSION:
        raise ValueError(
            f"config version {config.get('version') if isinstance(config, dict) else None!r} "
            f"unsupported (expected {CONFIG_VERSION})"
        )
    migrated = _migrate_header(config)
    _fill_missing(config, default_config())
    return _normalize_colors(config) or migrated


def _migrate_header(config: dict) -> bool:
    """ui.top_display -> ui.header, and drop the retired ui.show_tempo.

    Runs BEFORE _fill_missing, or the back-fill would hand the config a
    default header and the user's saved layout would silently vanish. The BPM
    slot in the header is the tempo toggle now, so a config that had tempo
    switched off keeps it off by starting with no BPM item.
    """
    ui = config.get("ui")
    if not isinstance(ui, dict):
        return False
    changed = False
    if "header" not in ui and "top_display" in ui:
        ui["header"] = ui.pop("top_display")
        changed = True
    if "show_tempo" in ui:
        if ui.pop("show_tempo") is False:
            slots = ui.get("header")
            if isinstance(slots, list):
                ui["header"] = [None if item == "bpm" else item for item in slots]
        changed = True
    return changed


# Pre-2026-07-06 configs used per-type color field names; the current model
# is off_color + on_color on every primary (secondaries: on_color only).
_OLD_ON_KEYS = ("pressed_color", "active_color", "color")
_OLD_OFF_KEYS = ("default_color", "inactive_color")


def _normalize_colors(config: dict) -> bool:
    changed = False
    for menu in config.get("menus", []):
        for slot in menu.get("slots", {}).values():
            primary = slot.get("primary")
            if primary:
                changed |= _normalize_action(primary, secondary=False)
            secondary = slot.get("secondary", {}).get("action") if slot.get("secondary") else None
            if secondary:
                changed |= _normalize_action(secondary, secondary=True)
    return changed


def _normalize_action(action: dict, secondary: bool) -> bool:
    if action.get("type") in (None, "nothing"):
        return False
    changed = False
    if "on_color" not in action:
        for key in _OLD_ON_KEYS:
            if key in action:
                action["on_color"] = action[key]
                break
        else:
            action["on_color"] = "#00FF66"
        changed = True
    if not secondary and "off_color" not in action:
        for key in _OLD_OFF_KEYS:
            if key in action:
                action["off_color"] = action[key]
                break
        else:
            action["off_color"] = "#303030"
        changed = True
    for key in _OLD_ON_KEYS + _OLD_OFF_KEYS + (("off_color",) if secondary else ()):
        if key in action:
            del action[key]
            changed = True
    return changed


def _fill_missing(config: dict, defaults: dict) -> None:
    """Recursively add default keys absent from a same-version config, so
    additive schema growth doesn't require a version bump."""
    for key, value in defaults.items():
        if key not in config:
            config[key] = value
        elif isinstance(value, dict) and isinstance(config[key], dict):
            _fill_missing(config[key], value)


def save_config(config: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    tmp_path = CONFIG_PATH.with_suffix(".json.tmp")
    with tmp_path.open("w") as f:
        json.dump(config, f, indent=2)
        f.write("\n")
    tmp_path.replace(CONFIG_PATH)
    log.info("config saved to %s", CONFIG_PATH)
