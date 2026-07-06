# Software Architecture

## Platform

- Raspberry Pi Zero 2 W
- Raspberry Pi OS Lite
- Run as systemd services
- Development over SSH

## Suggested Language/Stack

Recommended first version:
- Python 3
- Pygame or SDL2 for fullscreen display UI
- FastAPI or Flask for web app backend
- simple HTML/CSS/JS frontend
- python-rtmidi, mido, or ALSA sequencer for MIDI
- spidev for SPI ADC
- gpiozero/lgpio/RPi.GPIO for buttons

Alternative:
- Node.js backend + SDL/Python UI
- C++ for lower latency later

## Process Model

Option A: Single process
- easier first implementation
- one Python app handles GPIO, MIDI, UI, web server

Option B: Multi-process
- `controller-core.service`
- `controller-ui.service`
- `controller-web.service`

Recommended for v1:
- Single Python application with async/event-driven modules.
- Web server can run in same process or separate thread.

## Core Modules

### hardware/
- GPIO button reading
- power button reading
- SPI ADC reading
- expression detect pin

### midi/
- USB MIDI setup
- BLE MIDI setup
- send/receive MIDI messages
- parse CC/PC

### state/
- current menu
- button state
- effect status memory
- current program
- expression mode
- expression value

### ui/
- 1920x480 renderer
- button panels
- expression panel
- settings menu

### web/
- configuration pages
- REST API
- image upload
- preset import/export

### config/
- load/save JSON
- validate schema
- migrate config versions

### system/
- network/wireless settings
- safe shutdown hooks
- future battery hooks

## State Manager

The State Manager is the single source of truth.

Inputs:
- physical button events
- incoming MIDI
- web app config changes
- ADC values
- expression detect changes
- power button events

Outputs:
- outgoing MIDI
- UI updates
- web app live updates
- saved config/state

## UI Update Model

Do not redraw wastefully if not needed.
However, 1920x480 is manageable.

Target:
- 30 fps UI loop
- update immediately on state changes
- render text/images/status bars cleanly

## Persistence

Store:
- config JSON
- runtime effect states
- current program if desired
- uploaded image assets

Recommended directory:
```text
/opt/midi-controller/
  app/
  config/
    config.json
    state.json
  assets/
    images/
```

## Startup

Use systemd:
- start controller app after network and local filesystem
- ensure display UI launches at boot
- ensure MIDI endpoints are created before app starts if necessary
