"""Named preset files: whole-config snapshots stored on the device.

Presets live next to the live config (CONFIG_DIR/presets/<name>.json) so
deploys never clobber them. A preset is simply a full config JSON; loading
one validates/migrates it with the same code path as the live config
(Milestone 12.5).
"""

import copy
import json
import logging
import re

from config import loader
from config.defaults import default_config, strip_device_settings
from config.loader import prepare_config

log = logging.getLogger("controller.presets")

PRESET_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.-]{0,39}$")


def _presets_dir():
    return loader.CONFIG_DIR / "presets"


def validate_preset_name(name) -> str:
    if not isinstance(name, str) or not PRESET_NAME_RE.match(name.strip()):
        raise ValueError(
            "preset name must be 1-40 characters: letters, digits, spaces, . _ -"
        )
    return name.strip()


def preset_path(name: str):
    return _presets_dir() / f"{validate_preset_name(name)}.json"


def list_presets() -> list[dict]:
    directory = _presets_dir()
    if not directory.is_dir():
        return []
    presets = []
    for path in sorted(directory.glob("*.json")):
        presets.append({
            "name": path.stem,
            "modified": path.stat().st_mtime,
        })
    return presets


def save_preset(name: str, config: dict) -> None:
    directory = _presets_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = preset_path(name)
    tmp = path.with_suffix(".json.tmp")
    # Device-scoped settings stay out of preset files: loading them back (or
    # on another pedal) must not change device configuration.
    snapshot = copy.deepcopy(config)
    strip_device_settings(snapshot)
    snapshot["preset_name"] = validate_preset_name(name)
    with tmp.open("w") as f:
        json.dump(snapshot, f, indent=2)
        f.write("\n")
    tmp.replace(path)
    log.info("preset saved: %s", path)


def load_preset(name: str) -> dict:
    path = preset_path(name)
    if not path.exists():
        raise ValueError(f"no preset named {name!r}")
    with path.open() as f:
        config = json.load(f)
    prepare_config(config)
    config["preset_name"] = validate_preset_name(name)
    return config


def delete_preset(name: str) -> None:
    path = preset_path(name)
    if not path.exists():
        raise ValueError(f"no preset named {name!r}")
    path.unlink()
    log.info("preset deleted: %s", path)


def new_preset_config(name: str, blank: bool = False) -> dict:
    """A fresh default config for "start completely new preset". With blank,
    every button is unassigned (no demo slots) — everything else at defaults."""
    config = default_config()
    if blank:
        for menu in config["menus"]:
            menu["slots"] = {}
    config["preset_name"] = validate_preset_name(name)
    return config


def import_preset(name: str, raw_config) -> dict:
    """Validate an uploaded config JSON and store it as a preset."""
    if not isinstance(raw_config, dict):
        raise ValueError("preset config must be a JSON object")
    prepare_config(raw_config)
    save_preset(name, raw_config)
    return raw_config
