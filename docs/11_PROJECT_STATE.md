# Project State

Claude should update this file after every meaningful implementation session.

## Current Status

Not started.

## Hardware Confirmed

- Raspberry Pi Zero 2 W
- Raspberry Pi OS Lite
- 1920x480 HDMI display
- 10 momentary buttons
- SPI ADC with potentiometer
- momentary power button
- USB-C
- Bluetooth MIDI target

## Completed Milestones

None.

## Current Milestone

Milestone 1 — Raspberry Pi OS Lite Setup

## Decisions Made

- Button B10 is Shift/Menu and not assignable.
- Button B5 is assignable normally but Shift+B5 opens Menu 3.
- Holding Shift opens Menu 4.
- Four menus total.
- Nine assignable buttons per menu.
- Primary + optional secondary action system.
- Web app is hosted on controller.
- Effect CC state comes from returned MIDI feedback.
- Program Change state is one global current program number.
- Expression/pot display appears on right only when detected.

## Open Questions

- Exact GPIO pin numbers.
- Exact SPI ADC chip/model.
- Exact MIDI library.
- Exact UI framework.
- Exact BLE MIDI implementation path on Raspberry Pi OS Lite.
- Exact screen mounting/brightness considerations.

## Risks

- BLE MIDI setup may require system-level BlueZ work.
- USB MIDI gadget configuration may require boot/config changes.
- 1920x480 display configuration may need custom HDMI mode.
- Raw LCD/driver board may have mounting/brightness quirks.
- Power button safe shutdown needs hardware support for true power cut.

## Next Actions

1. Create repository.
2. Add Python app skeleton.
3. Add hardware constants.
4. Add config schema defaults.
5. Create systemd service.
