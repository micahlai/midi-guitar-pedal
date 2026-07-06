# Project State

Claude should update this file after every meaningful implementation session.

## Current Status

Milestone 2 complete (2026-07-05). 1920x480 display running fullscreen via
pygame/KMSDRM with the 5x2 button grid and expression strip placeholder.

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

### Milestone 2 — Display Bring-Up (2026-07-05)
- Panel EDID only advertises 720x480/640x480; forced the real mode with
  `video=HDMI-A-1:1920x480M@60D` in `/boot/firmware/cmdline.txt` (CVT timings,
  backup at `cmdline.txt.bak`). Panel accepted it; fb is 1920x480.
- UI framework decided: pygame 2.6.1 on SDL2 KMSDRM (no X/Wayland). Installed
  via apt `python3-pygame`; venv rebuilt with `--system-site-packages`.
  Also required `libegl-mesa0 libegl1 libgles2` (Lite image lacks the EGL/GLES
  runtime, symptom: "EGL not initialized").
- `ui/renderer.py`: fullscreen 30 fps render thread; 5x2 panel grid with
  placeholder labels B1-B9 + required bottom status rectangles; B10 panel shows
  current menu (and a highlight border when Shift held); right expression strip
  placeholder with vertical value bar; theme colors from config.
- Debug facility: `kill -USR1 <pid>` saves the current frame to
  `/tmp/controller-frame.png` — used over ssh to verify screen contents.
- Verified by screenshot: grid + EXP strip render correctly at 1920x480.
- **vc4 alpha scanout bug found and fixed**: SDL's plain 2D present leaves the
  ARGB scanout plane's alpha at zero and vc4 composites it as transparent —
  software looks healthy (screenshots fine, CRTC active) but the physical
  screen is black. Diagnosed with modetest (kernel path OK) vs pygame fill
  (black) vs GL clear with alpha=1 (visible). Fix: `ui/gles.py` presents the
  canvas through GLES2 with a shader forcing alpha to 1.0.
- Debug on any monitor: renderer picks the smallest advertised mode fitting
  1920x480 on both axes and centers the unscaled canvas in it (e.g. band in
  the middle of a 1080p desk monitor); falls back to a centered crop if the
  display can't fit it.
- ~90% of one core at constant 30 fps (canvas → RGBA → GL texture upload per
  frame); dirty-flag/idle throttling deferred to Milestone 16 (polish).
- Gotcha: monitors/PiP scalers can serve stale or bogus EDIDs; a swap while
  the app runs needs a service restart (SDL doesn't re-modeset on hotplug).

## Current Milestone

Milestone 3 — GPIO Buttons

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
- Exact BLE MIDI implementation path on Raspberry Pi OS Lite.
- Exact screen mounting/brightness considerations.

## Risks

- BLE MIDI setup may require system-level BlueZ work.
- USB MIDI gadget configuration may require boot/config changes.
- Raw LCD/driver board may have mounting/brightness quirks.
- Power button safe shutdown needs hardware support for true power cut.
- Pi Zero 2 W has ~424 MB RAM total; keep dependency footprint small.

## Next Actions

1. Milestone 3: gpiozero/lgpio button reading for all 10 buttons + debounce.
2. Event model: press, release, hold.
3. Shift/Menu behavior: toggle Menu 1/2, Shift+B5 → Menu 3, Shift hold → Menu 4.
4. Confirm actual wiring matches draft GPIO numbers in `hardware/constants.py`.
