# Config Schema Draft

This is an initial JSON shape. It can be refined during implementation.

```json
{
  "version": 1,
  "device": {
    "name": "Pi MIDI Foot Controller",
    "hostname": "midi-controller"
  },
  "ui": {
    "screen_width": 1920,
    "screen_height": 480,
    "expression_panel_width_ratio": 0.12,
    "theme": {
      "background": "#050505",
      "panel_background": "#111111",
      "text": "#FFFFFF",
      "disabled": "#333333"
    }
  },
  "buttons": {
    "shift_button": 10,
    "menu3_combo_button": 5,
    "shift_hold_seconds": 2.0,
    "secondary_hold_default_seconds": 1.5,
    "debounce_ms": 30
  },
  "midi": {
    "usb_enabled": true,
    "ble_enabled": true,
    "default_channel": 1,
    "program_display_base": 1
  },
  "expression": {
    "detect_enabled": true,
    "panel_label": "EXP",
    "send_deadband": 1,
    "poll_interval_ms": 10,
    "return_alpha": 0.15,
    "return_interval_ms": 30,
    "return_stop_threshold": 0.5
  },
  "menus": [
    {
      "id": 1,
      "name": "Menu 1",
      "slots": {}
    },
    {
      "id": 2,
      "name": "Menu 2",
      "slots": {}
    },
    {
      "id": 3,
      "name": "Menu 3",
      "slots": {}
    },
    {
      "id": 4,
      "name": "Menu 4",
      "slots": {}
    }
  ]
}
```

## Button Slot Draft

```json
{
  "physical_button": 1,
  "primary": {
    "type": "effect_cc",
    "midi_channel": 1,
    "cc_number": 21,
    "off_color": "#303030",
    "on_color": "#00FF66",
    "label": "DRIVE",
    "image_asset_id": null
  },
  "secondary": {
    "enabled": true,
    "hold_seconds": 1.5,
    "action": {
      "type": "program_change",
      "midi_channel": 1,
      "program_number": 3,
      "inactive_color": "#303030",
      "active_color": "#3399FF",
      "label": "Lead"
    }
  }
}
```
