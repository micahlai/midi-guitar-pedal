"""Default configuration, matching docs/12_CONFIG_SCHEMA_DRAFT.md."""

import copy

CONFIG_VERSION = 1

DEFAULT_CONFIG = {
    "version": CONFIG_VERSION,
    "preset_name": "Default",
    "device": {
        "name": "Pi MIDI Foot Controller",
        "hostname": "guitar-pedal",
    },
    "ui": {
        "screen_width": 1920,
        "screen_height": 480,
        # Header strip, left to right: 5 positions, one item each (see
        # logic/header.py). null = that position shows nothing. The default
        # reproduces the original header minus the power readout. BPM's
        # presence here is also what enables MIDI clock tracking.
        "header": ["patch", None, None, None, "bpm"],
        "expression_panel_width_ratio": 0.12,
        # 10 shared palette slots. Action colors may reference one as
        # "palette:N" (0-9); editing a slot recolors every reference.
        "color_palette": [
            "#00FF66", "#00CCFF", "#FF6600", "#3399FF", "#FFCC00",
            "#CC66FF", "#FF3355", "#66FF99", "#FFFFFF", "#303030",
        ],
        # Optional user labels per palette slot (shown in the editor's color
        # pickers); empty string -> the UI falls back to "Palette N".
        "color_palette_labels": ["", "", "", "", "", "", "", "", "", ""],
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
        "power_double_press_ms": 400,
        "power_hold_seconds": 3.0,
    },
    "web": {
        "enabled": True,
        "port": 8080,
    },
    "hotspot": {
        "ssid": "GuitarPedal",
        "password": "pedalsetup",
        # Self-host after this long with no Wi-Fi, so a pedal that boots away
        # from any known network is still reachable for configuration.
        "auto_fallback": True,
        "fallback_seconds": 45,
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
        {
            "id": 1,
            "name": "Menu 1",
            # Demo assignments exercising every action type; all editable via
            # config.json (and the web app in later milestones).
            # Color model: every primary action has off_color + on_color;
            # secondary actions have on_color only (see ui/renderer.py
            # _slot_status_color for the display rules).
            "slots": {
                "1": {
                    "primary": {
                        "type": "effect_cc", "midi_channel": 1, "cc_number": 21,
                        "off_color": "#303030", "on_color": "#00FF66",
                        "label": "DRIVE", "image_asset_id": None,
                    },
                    "secondary": {
                        "enabled": True,
                        "hold_seconds": 1.5,
                        "action": {
                            "type": "program_change", "midi_channel": 1,
                            "program_number": 3, "on_color": "#3399FF",
                            "label": "SOLO",
                        },
                    },
                },
                "2": {"primary": {
                    "type": "effect_cc", "midi_channel": 1, "cc_number": 22,
                    "off_color": "#303030", "on_color": "#00CCFF",
                    "label": "DELAY", "image_asset_id": None,
                }},
                "3": {"primary": {
                    "type": "action_cc", "midi_channel": 1, "cc_number": 23,
                    "off_color": "#303030", "on_color": "#FF6600",
                    "label": "TAP", "image_asset_id": None,
                }},
                "4": {"primary": {
                    "type": "program_change", "midi_channel": 1, "program_number": 1,
                    "off_color": "#303030", "on_color": "#3399FF",
                    "label": "RHYTHM", "image_asset_id": None,
                }},
                "5": {"primary": {
                    "type": "program_change", "midi_channel": 1, "program_number": 2,
                    "off_color": "#303030", "on_color": "#3399FF",
                    "label": "LEAD", "image_asset_id": None,
                }},
                "6": {"primary": {
                    "type": "expression_pedal", "midi_channel": 1, "cc_number": 7,
                    "off_color": "#303030", "on_color": "#FFCC00",
                    "label": "VOLUME", "image_asset_id": None,
                    "value_min": 0, "value_max": 127, "reverse": False,
                    "has_home": False, "home_value": 0,
                }},
                "7": {"primary": {
                    "type": "expression_pedal", "midi_channel": 1, "cc_number": 11,
                    "off_color": "#303030", "on_color": "#CC66FF",
                    "label": "WAH", "image_asset_id": None,
                    "value_min": 0, "value_max": 127, "reverse": False,
                    "has_home": True, "home_value": 0,
                }},
                "8": {"primary": {
                    "type": "nothing", "label": "", "color": "#1A1A1A",
                }},
                "9": {"primary": {
                    "type": "effect_cc", "midi_channel": 1, "cc_number": 24,
                    "off_color": "#303030", "on_color": "#00FF66",
                    "label": "REVERB", "image_asset_id": None,
                }},
            },
        },
        {"id": 2, "name": "Menu 2", "slots": {}},
        {"id": 3, "name": "Menu 3", "slots": {}},
        {"id": 4, "name": "Menu 4", "slots": {}},
    ],
}


def default_config() -> dict:
    return copy.deepcopy(DEFAULT_CONFIG)


# (section, key) config paths that belong to THIS DEVICE, not to a preset:
# hardware identity, transports, wiring/timing calibration. Preset files are
# saved without them and loading/importing a preset never changes them —
# everything else in the config travels with the preset.
DEVICE_SETTING_PATHS = (
    ("device", "name"),
    ("device", "hostname"),
    ("web", "enabled"),
    ("web", "port"),
    ("hotspot", "ssid"),
    ("hotspot", "password"),
    ("hotspot", "auto_fallback"),
    ("hotspot", "fallback_seconds"),
    ("midi", "usb_enabled"),
    ("midi", "ble_enabled"),
    ("buttons", "debounce_ms"),
    ("buttons", "power_double_press_ms"),
    ("buttons", "power_hold_seconds"),
    ("expression", "detect_enabled"),
    ("expression", "send_deadband"),
    ("expression", "poll_interval_ms"),
    ("expression", "return_alpha"),
    ("expression", "return_interval_ms"),
    ("expression", "return_stop_threshold"),
    ("ui", "header"),
    ("ui", "screen_width"),
    ("ui", "screen_height"),
)


def strip_device_settings(config: dict) -> None:
    """Remove the device-scoped keys in place (preset save/export)."""
    for section, key in DEVICE_SETTING_PATHS:
        section_dict = config.get(section)
        if isinstance(section_dict, dict):
            section_dict.pop(key, None)


def copy_device_settings(source: dict, target: dict) -> None:
    """Overlay source's device-scoped settings onto target — applied to a
    freshly loaded/imported preset so it can't change device configuration."""
    for section, key in DEVICE_SETTING_PATHS:
        section_dict = source.get(section)
        if isinstance(section_dict, dict) and key in section_dict:
            target.setdefault(section, {})[key] = copy.deepcopy(section_dict[key])
