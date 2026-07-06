"""Default configuration, matching docs/12_CONFIG_SCHEMA_DRAFT.md."""

import copy

CONFIG_VERSION = 1

DEFAULT_CONFIG = {
    "version": CONFIG_VERSION,
    "device": {
        "name": "Pi MIDI Foot Controller",
        "hostname": "guitar-pedal",
    },
    "ui": {
        "screen_width": 1920,
        "screen_height": 480,
        "expression_panel_width_ratio": 0.12,
        "theme": {
            "background": "#050505",
            "panel_background": "#111111",
            "text": "#FFFFFF",
            "disabled": "#333333",
        },
    },
    "buttons": {
        "shift_button": 10,
        "menu3_combo_button": 5,
        "shift_hold_seconds": 2.0,
        "secondary_hold_default_seconds": 1.5,
        "debounce_ms": 30,
    },
    "midi": {
        "usb_enabled": True,
        "ble_enabled": True,
        "default_channel": 1,
        "program_display_base": 1,
    },
    "expression": {
        "detect_enabled": True,
        "panel_label": "EXP",
        "send_deadband": 1,
        "poll_interval_ms": 10,
        "return_alpha": 0.15,
        "return_interval_ms": 30,
        "return_stop_threshold": 0.5,
    },
    "menus": [
        {"id": 1, "name": "Menu 1", "slots": {}},
        {"id": 2, "name": "Menu 2", "slots": {}},
        {"id": 3, "name": "Menu 3", "slots": {}},
        {"id": 4, "name": "Menu 4", "slots": {}},
    ],
}


def default_config() -> dict:
    return copy.deepcopy(DEFAULT_CONFIG)
