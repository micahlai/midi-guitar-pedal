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

    if config.get("version") != CONFIG_VERSION:
        raise ValueError(
            f"config version {config.get('version')} unsupported "
            f"(expected {CONFIG_VERSION}); migrations not implemented yet"
        )
    return config


def save_config(config: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    tmp_path = CONFIG_PATH.with_suffix(".json.tmp")
    with tmp_path.open("w") as f:
        json.dump(config, f, indent=2)
        f.write("\n")
    tmp_path.replace(CONFIG_PATH)
    log.info("config saved to %s", CONFIG_PATH)
