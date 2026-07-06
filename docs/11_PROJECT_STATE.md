# Project State

Claude should update this file after every meaningful implementation session.

## Current Status

Milestone 1 complete (2026-07-05). Repository skeleton created, Pi provisioned,
app runs at boot under systemd and logs a heartbeat to the journal.

## Hardware Confirmed

- Raspberry Pi Zero 2 W
- Raspberry Pi OS Lite — Raspbian 13 (trixie), 32-bit, Python 3.13.5
- hostname `guitar-pedal`, user `micah`, key-based SSH (`ssh pedal` alias)
- 1920x480 HDMI display
- 10 momentary buttons
- SPI ADC with potentiometer
- momentary power button
- USB-C
- Bluetooth MIDI target

## Completed Milestones

### Milestone 1 — Raspberry Pi OS Lite Setup (2026-07-05)
- SSH with key auth working; passwordless sudo available.
- Repo skeleton: `app/main.py` entrypoint, `hardware/constants.py` (all GPIO/SPI
  pins centralized), `config/` (defaults per schema draft + JSON load/save),
  `state/manager.py`, placeholder `ui/`, `midi/`, `web/` modules.
- `systemd/midi-controller.service` installed and enabled; verified via reboot
  that the app starts at boot and heartbeats to the journal.
- Pi provisioned: `/opt/midi-controller/{app,config,assets/images}` owned by
  `micah`, venv at `/opt/midi-controller/venv` (no third-party deps yet).
- `deploy.sh` rsyncs `app/` + service unit to the Pi and restarts the service.
- Default `config.json` auto-created at `/opt/midi-controller/config/config.json`.

## Current Milestone

Milestone 2 — Display Bring-Up

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
- Development workflow: edit on Mac (repo is source of truth), `./deploy.sh`
  rsyncs to Pi and restarts the service; Claude Code drives the Pi over
  non-interactive `ssh pedal` commands.
- Single-process Python app (architecture doc Option A); modules started/stopped
  from `main.py`.
- Config JSON lives outside the deployed app dir so deploys never clobber it;
  path overridable via `CONTROLLER_CONFIG_DIR` for local testing.
- GPIO pins use the draft numbers from the hardware spec until wiring is final.

## Open Questions

- Exact GPIO pin numbers (draft numbers from hardware spec are in
  `hardware/constants.py`; confirm against actual wiring).
- Exact SPI ADC chip/model.
- Exact MIDI library.
- Exact UI framework (pygame vs SDL2 direct — decide in Milestone 2).
- Exact BLE MIDI implementation path on Raspberry Pi OS Lite.
- Exact screen mounting/brightness considerations.

## Risks

- BLE MIDI setup may require system-level BlueZ work.
- USB MIDI gadget configuration may require boot/config changes.
- 1920x480 display configuration may need custom HDMI mode.
- Raw LCD/driver board may have mounting/brightness quirks.
- Power button safe shutdown needs hardware support for true power cut.
- Pi Zero 2 W has ~424 MB RAM total; keep dependency footprint small.

## Next Actions

1. Milestone 2: configure 1920x480 HDMI output (KMS/`/boot/firmware/config.txt`).
2. Choose UI framework (pygame on KMSDRM likely) and install into venv.
3. Fullscreen render loop: 5x2 button grid + expression strip placeholder.
