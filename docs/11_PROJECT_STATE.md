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

### Milestone 3 — GPIO Buttons (2026-07-05, pending physical button test)
- `hardware/buttons.py`: gpiozero (lgpio) reading of all 10 buttons, internal
  pull-ups, config-driven debounce (30 ms), raw press/release events with
  monotonic timestamps pushed to a thread-safe queue.
- `logic/menu.py`: pure logic, no hardware imports — shift toggle Menu 1<->2
  (Menu 3/4 short-press returns to Menu 1), Shift+B5 -> Menu 3 (B5 suppressed,
  Menu 4 timer cancelled), Shift hold 2.0 s -> Menu 4 (release then inert),
  B1-B9 press/release/hold-threshold events via on_action_event callback for
  later milestones.
- `main.py` loop reworked: 10 ms event/tick loop feeding MenuLogic; heartbeat
  now every 30 s.
- `tests/test_menu_logic.py`: 9 unit tests covering the shift/menu matrix, all
  passing (run from `app/`: `python3 -m unittest discover tests`).
- Deployed; service logs "watching 10 buttons". Physical press verification
  awaits wired buttons.

### Milestone 3 addendum — GPIO debugging (2026-07-05)
- gpiozero `bounce_time` on the lgpio backend silently drops ALL events;
  debounce is now done in `ButtonReader` (dedupe + 30 ms window), Buttons are
  created without bounce_time. MenuLogic ignores orphaned shift releases.
- User remapped pins in `hardware/constants.py` (B1=6, B2=13, B3=19, B4=5,
  B5=23, shift=26). NOTE: B5 shares GPIO 23 with the draft expression-detect
  pin — expression detect reassigned to GPIO 25 in Milestone 5.
- Physical presses verified NOT reaching any of the 28 GPIOs (gpiomon, level
  polls); wiring issue on user's bench (ground return / tact switch
  orientation suspected). Software path verified end to end.

### Milestone 4 — Power Button UI Behavior (2026-07-05, pending physical test)
- Power button (GPIO 24) read as button 0 through the same ButtonReader.
- `logic/power.py`: double press (400 ms window) toggles settings menu; hold
  3.0 s logs shutdown stub. `logic/settings.py`: B6/B7 navigate, B9 select,
  B10 exit (Exit item or B10 closes). Both pure logic.
- Settings screen in renderer with footswitch legend; verified by headless
  render. Config gained power_double_press_ms / power_hold_seconds; loader now
  back-fills missing keys from defaults (additive schema growth, same version).
- 20 unit tests passing.

### Milestone 5 — SPI ADC Potentiometer (2026-07-05, pending pot hardware test)
- `hardware/adc.py`: MCP3008 assumed (10-bit, swap `_read_raw()` if the real
  chip differs); poll thread at 10 ms, EMA smoothing (alpha 0.3), writes
  normalized 0-1 to state. Detect pin GPIO 25 (moved off 23 = user's B5), low
  = plugged in via internal pull-up; drives state.expression_detected.
- UI hides the expression strip and gives the grid full width when not
  detected (verified by screenshot); bar direction respects reverse; home
  value drawn as a marker line.
- `dtparam=spi=on` added; `/dev/spidev0.0` present; ADC thread running.

### Milestone 6 — Config Data Model (2026-07-05)
- `config/model.py` slot/action accessors; defaults now populate Menu 1 with
  demo assignments covering all five action types (DRIVE/DELAY effect_cc,
  TAP action_cc, RHYTHM/LEAD program_change, VOLUME/WAH expression_pedal
  incl. has_home, B8 nothing, REVERB effect_cc).
- Renderer is fully config-driven: labels, per-type status bar colors
  (effect state / pressed / current program / active expression mode),
  "Hold for X" hint when a secondary exists. Verified by screenshot.
- NOTE: Pi config.json predating the slots was regenerated from defaults;
  loader back-fills missing keys but does not merge menu contents.

### Milestone 7 — Basic MIDI Send (2026-07-05, pending DAW verification)
- USB MIDI gadget via configfs (`scripts/setup-usb-midi-gadget.sh` +
  `usb-midi-gadget.service`, `dtoverlay=dwc2,dr_mode=peripheral` under [all]
  — beware the [cm5] section already has a dwc2 line). ALSA port `f_midi`
  hw:1,0 confirmed; app opens it via mido/python-rtmidi (apt packages).
- `logic/actions.py`: button events -> per-type dispatch (effect_cc/action_cc
  send CC 127 on press, program_change sends PC, expression_pedal selects
  mode, nothing inert). Secondary-hold semantics deferred to Milestone 10.
- `logic/expression.py`: pot -> CC with min/max/reverse mapping, clamp,
  deadband; exponential home-return (alpha 0.15 / 30 ms / stop 0.5) when
  switching away from a has_home mode; pot movement cancels an active return.
- 31 unit tests passing.
- USB enumeration verified (2026-07-05): Mac enumerates "Pi MIDI Foot
  Controller" (UDC state `configured`) when the laptop feeds the Pi's USB
  data port directly (single cable, also powering the Pi). With separate
  wall power on PWR IN + laptop on the data port it read `not attached` —
  retest dual-power arrangement if needed later. Overlay is plain
  `dtoverlay=dwc2` (OTG default). Test CC/PC messages sent via ALSA seq
  (rawmidi is held by the app; use mido/seq for manual test sends).
- Pending: physical buttons (Milestone 3 wiring issue) to fire real actions;
  pot movement on screen.

## Current Milestone

Milestone 8 — MIDI Receive and State Sync

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
