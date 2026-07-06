# Raspberry Pi Zero 2 W MIDI Foot Controller — Claude Project Pack

This folder is intended to be copied into a Claude Code project as the planning/spec source of truth.

Target platform:
- Raspberry Pi Zero 2 W
- Raspberry Pi OS Lite
- Development over SSH
- 1920×480 HDMI display
- 10 fixed momentary footswitches
- SPI ADC connected to one potentiometer
- momentary power button
- USB-C wired MIDI/config/power connection
- Bluetooth MIDI support

Core idea:
The controller is a self-contained guitar/pedalboard MIDI controller for MainStage or a DAW. It sends MIDI over USB-C and/or Bluetooth, receives MIDI feedback, updates a 1920×480 UI, and exposes a local web app for configuration over the device network.

Important fixed hardware:
- 10 physical button positions never change.
- Bottom-right button is the Shift/Menu button.
- Top-right button is assignable normally, but Shift + top-right opens Menu 3.
- Holding Shift for a configurable duration opens Menu 4.
- Power button hold controls device power, double press opens Settings.
- SPI ADC reads a potentiometer/expression-style analog value.

Recommended project workflow:
1. Read `01_PROJECT_BRIEF.md`.
2. Read `02_HARDWARE_SPEC.md`.
3. Read `03_UI_SPEC.md`.
4. Read `04_MIDI_SPEC.md`.
5. Read `05_CONFIGURATION_WEB_APP_SPEC.md`.
6. Implement milestones in `10_ROADMAP_MILESTONES.md`.
7. Update `11_PROJECT_STATE.md` after every meaningful coding session.
