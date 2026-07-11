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
- SPI ADC: MCP3008 confirmed (2026-07-09), wired to SPI0 — MOSI GPIO 10,
  MISO GPIO 9, SCLK GPIO 11, CS on CE0 (GPIO 8); pot on channel 7
  (constants.py is the source of truth)
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

### Milestone 8 — MIDI Receive and State Sync (2026-07-05)
- Engine opens the f_midi input with a callback; CC/PC messages flow into the
  main event queue (now tagged: ("button", ...) / ("midi", msg)).
- `logic/midi_in.py`: incoming CC updates effect_states[(channel, cc)] for
  CCs that some effect_cc assignment listens to (0=off, >0=on); incoming PC
  stores the global current program.
- VERIFIED END TO END over USB: Mac (mido venv) sent CC21/CC22/PC/CC22=0 to
  "Pi MIDI Foot Controller"; journal logged each; screenshot showed DRIVE bar
  green, DELAY back off, LEAD bar active.

### Milestone 9 — Action Types (2026-07-05)
- All five primary types dispatch in `logic/actions.py` (shared for primary
  and secondary): effect_cc/action_cc send CC 127, program_change sends PC,
  expression_pedal selects the pot mode, nothing is inert.
- Note-style CC naming (F#3) deferred to the web app UI (display concern).

### Milestone 10 — Secondary Hold Actions (2026-07-05)
- Hold timing moved from MenuLogic into ActionLogic (per-slot hold_seconds,
  default 1.5 s). With a secondary: primary defers; quick release fires
  primary, hold fires secondary once and release is inert.
- expression_mode is now (menu_id, button_num, "primary"|"secondary") so a
  secondary expression assignment can be the active pot mode.
- Demo config: B1 DRIVE gained a secondary program_change "SOLO" (hold 1.5 s);
  UI "Hold for SOLO" hint verified by screenshot. Pi config.json regenerated.
- 39 unit tests passing.

### Post-M10 adjustments (2026-07-05, user-directed)
- Shift panel shows the current program ("PGM n", raw 0-127) under the menu
  number, updated only from incoming PC.
- effect_cc and action_cc now SEND MIDI NOTES (note_on velocity 127); the
  cc_number field holds the note number (MainStage-style mapping).
  expression_pedal still sends CC (continuous).
- Feedback accepted as CC or notes interchangeably: note_off / velocity 0 /
  CC 0 = off, anything else = on. Buttons remain fire-and-forget; ALL state
  comes from incoming MIDI regardless of source.
- Verified live against a running MainStage session over USB (note echoes,
  CC 11, PCs all tracked). 48 unit tests passing.
- NOTE: every incoming message is logged at INFO; a busy DAW session makes
  the journal chatty — consider demoting "MIDI in" to DEBUG after bring-up.

### Milestone 11 — Web App Basics (2026-07-05)
- `web/server.py`: stdlib ThreadingHTTPServer (no new deps) on port 8080
  (config `web.enabled`/`web.port`, back-filled by the loader), daemon thread,
  started/stopped from main. Bind failure logs an error but doesn't kill the
  controller.
- Endpoints: `GET /` single-page editor, `GET /api/config` full config,
  `POST /api/slot` `{menu_id, button_num, type, label}` -> validates, applies,
  save_config()s, returns the updated slot.
- Edit semantics: same-type edits only change the label (tuned CC numbers /
  colors survive); a type change installs a fresh per-type template using
  `midi.default_channel`. Slots are created on demand in empty menus.
- Live-update safety: the edit is one dict-item assignment on the shared
  config (atomic under the GIL; renderer/logic read config per frame). If the
  edited slot's primary was the ACTIVE expression mode and is no longer
  expression_pedal, `state.expression_mode` is cleared — otherwise
  ExpressionLogic would KeyError on `value_min` and kill the main loop.
- `web/static/index.html`: vanilla-JS dark-theme editor — 4 menu tabs, 5x2
  grid (B10 shown as non-editable Shift), per-slot label input + type
  dropdown, saves on change, color swatch + "Note/PC/CC n · ch n" summary.
- VERIFIED END TO END from the Mac at `http://guitar-pedal.local:8080`:
  edited B2 label and set B8 nothing->program_change via the API; screenshot
  showed ECHO/CHORUS on the physical layout, config.json on the Pi persisted
  both, service survived. Demo edits reverted after.
- 60 unit tests passing (12 new: edit logic + HTTP round-trip on port 0 with
  an injected save stub).

### Milestone 12 — Full Web App Editor (2026-07-05)
- API reworked (old `/api/slot` replaced): `POST /api/slot/primary` and
  `/api/slot/secondary` take FULL action dicts, validated per type
  (channel 1-16, note/CC/PC 0-127, #RRGGBB colors normalized to uppercase,
  bools; unknown fields stripped). Secondary: types restricted to
  effect_cc/action_cc/program_change, no image, hold_seconds 0.2-10,
  requires a primary. `/api/slot/secondary/remove` deletes it.
- `POST /api/settings`: shift_hold_seconds (0.5-10),
  secondary_hold_default_seconds (0.2-10), expression_panel_width_ratio
  (0.05-0.3). `GET /api/status` returns live menu/program/expression state
  for the sidebar preview (polled every 2 s).
- Stale-cache fixes so web edits apply live without restart: MenuLogic
  shift hold, ActionLogic default secondary hold, and renderer expression
  panel ratio are now read from config at point of use (were cached at
  init). The expression-mode guard now also covers secondary edits/removal.
- Editor UI: slot cells (label, type/note/channel summary, swatch, "Hold Xs
  for Y" line) open a modal with Primary/Secondary tabs per spec 5 —
  type-specific field forms, add/remove secondary, per-slot hold seconds.
  Sidebar: hold settings, expression panel width slider, live status box
  (menu, program, pedal detected, active mode, pot value bar).
- Client keeps per-type templates; switching type in the modal carries over
  label + channel. Save posts primary, then secondary set/remove as needed.
- VERIFIED against the Pi: full-field expression primary, secondary with
  custom hold, settings write, status endpoint, and a 400 on an
  expression-type secondary. Demo edits reverted afterwards — NOTE: the
  user already has real edits in Menu 1 (made via the M11 editor, see
  journal "web edit" lines), so the Pi config is user data now; don't
  regenerate it from defaults.
- 66 unit tests passing (18 web: validation, slot edits, settings, HTTP).

### Post-M12 — program number display base (2026-07-05, user-directed)
- User's rig (MainStage) numbers patches from 1 but MIDI PC is 0-based;
  "sending 1 sent 2". `midi.program_display_base` (0 or 1, default 1) now
  actually drives behavior:
  - config stores program_number AS DISPLAYED (base..127+base; web editor
    rejects 0 when base is 1); the wire always sends number - base
    (clamped 0-127) in ActionLogic.
  - renderer: PGM panel shows wire + base; program_change active-color
    compares current_program (wire, from feedback) == stored - base.
  - `/api/settings` accepts program_display_base; changing it SHIFTS every
    stored program_number (primaries + secondaries, all menus) by the delta
    so the wire values / targeted patches stay identical. Web sidebar gained
    a "Program numbers start at" selector (re-fetches config after, since
    numbers move).
- Existing user config needed no migration: numbers were already entered
  1-based with base=1 backfilled, so the fix applied immediately.
- Verified on the Pi: base 1->0->1 round-trips the user's stored numbers
  (1,2,3,4 -> 0,1,2,3 -> 1,2,3,4); PC 0 rejected at base 1 ("must be an
  integer 1-128"). 73 unit tests passing.

### Post-M12 — inline editor + unified color model (2026-07-06, user-directed)
- Web editor: modal removed; all 9 buttons' full settings render as cards
  below the panel grid. Plain click on a panel cell scrolls to its card;
  SHIFT-CLICK selects multiple — any field change on a selected button
  mirrors to all selected (labels intentionally excluded) and each mirrored
  slot auto-saves. Everything saves on change (no Save button).
- Color model: every primary action now has off_color + on_color (all
  types; nothing keeps its single color); secondary actions have on_color
  ONLY. Old per-type fields (default/pressed, inactive/active, expression
  color) are migrated by the loader on first run (`_normalize_colors`,
  logged + saved back) — verified against the user's live Pi config.
- Status bar display rules (renderer `_slot_status_color`): secondary
  active -> secondary on_color; primary active -> primary on_color; BOTH
  active -> flicker between the two on_colors with a 2 s period; neither ->
  primary off_color. "Active" per type: effect_cc = feedback state,
  program_change = current program (base-aware), expression = active pot
  mode (role-aware), action_cc = held (primary) / held-after-secondary-
  fired (secondary, via new state.secondary_pressed set maintained by
  ActionLogic).
- expression_pedal is now allowed as a SECONDARY type (web + validation);
  M10 logic already supported (menu, button, "secondary") pot modes.
- 87 unit tests passing (new: status color rules incl. flicker with mocked
  clock, color migration, secondary_pressed tracking).
- NOTE: flicker verified by unit test only — needs two simultaneously
  active assignments on one slot (e.g. effect feedback + matching PC) to
  see live; physical buttons still unwired.

### Post-M12 — web UI tab restructure (2026-07-06, user-directed)
- Tabs are now: Overview | Menu 1-4 | Global Settings (sidebar removed;
  hold/MIDI/expression settings + live status moved into the Global tab).
- Overview tab: all 36 slots as compact panels grouped by menu, swatches in
  fixed order primary-on · secondary-on · off; clicking a panel jumps to
  that menu tab with the button's in-depth card selected + scrolled into
  view.
- Menu tabs: the in-depth cards ARE the layout now — 5x2 grid matching the
  physical board (B10 dashed placeholder), scaling with window width
  (page min-width 1000px). Clicking anywhere on a card that isn't an input
  selects it; shift-click multi-selects; mirrored editing unchanged.

### Milestone 12.5 — Web App Editor Additions (2026-07-06)
- **Color palette**: `ui.color_palette` (10 slots). Action colors are literal
  `#RRGGBB` OR `"palette:N"` references — linked colors; editing a palette
  slot (new Palette tab, `POST /api/palette`) recolors every reference.
  `config/model.py resolve_color()` resolves refs at point of use (renderer
  `_color()` wrapper, web `resolveColor()`); card color fields are a 10-swatch
  picker + custom (unlinked) color input.
- **Menu names**: `POST /api/menu {menu_id, name}` (empty -> "Menu n"); name
  input on each menu tab; tabs/overview use it. Display B10 panel shows the
  menu NAME (auto-fit via new `_fit_text` size-stepping helper) with "MENU n"
  and "PGM n" beneath in the small font.
- **Duplicate warnings** (web, non-blocking): note space (effect_cc+action_cc
  cc_number) and program space checked across all menus/roles; warning names
  the other assignment; "Use next available note" button for note types.
- **Presets**: `config/presets.py`, files in CONFIG_DIR/presets/<name>.json
  (deploys never touch them). Presets tab: save/save-as/load/delete/new/
  import (client-side JSON file read) + export (Content-Disposition download,
  `GET /api/preset/export?name=`). `preset_name` top-level config key,
  editable in Global Settings; loading validates via `loader.prepare_config`
  (refactored out of load_config). Name whitelist regex blocks path tricks.
- **Undo/redo**: server-side full-config snapshots (in-memory, cap 100,
  cleared on restart per spec) on EVERY mutating endpoint via
  `WebServer._mutate` (also restores the snapshot if an edit raises
  half-applied). `POST /api/undo|/api/redo` return the full config; header
  buttons + Cmd/Ctrl(+Shift)+Z.
- `install_config()` swaps whole configs (preset load/new, undo/redo) into
  the shared dict IN PLACE — modules hold references to the config object —
  and clears a stale expression mode. Renderer `theme` became a live property
  for the same reason.
- Verified on the Pi: palette/menu/undo/redo/preset save/export round-trips
  over HTTP, bad preset name rejected, screenshot of B10 menu-name panel;
  all test edits reverted (user config preserved). 113 unit tests passing.

### Milestone 13 — Image Upload (2026-07-06)
- No Pillow / no server-side image lib (RAM stays flat on the Zero 2 W): the
  BROWSER resizes/compresses (canvas, max 480x240, shrinks until <120 KB PNG)
  and posts a data URL; `web/images.py` validates (PNG magic, base64, 128 KB
  cap, id whitelist regex) and stores under
  `/opt/midi-controller/assets/images/<slug>-<hexts>.png` (outside the deploy
  path; `CONTROLLER_ASSETS_DIR` overrides for tests). Asset ids are
  self-describing (slug+timestamp) so renderer caches never go stale.
- API: `GET /api/images`, `GET /images/<id>.png`, `POST /api/image`
  {name, data}, `POST /api/image/delete` {id} — delete clears all config
  references first (undoable mutation), then removes the file.
- Web: new Images tab — file upload, LIBRARY grid with thumbnails/delete,
  and the IMAGE CREATOR (text + font/style/color/optional solid background
  flattened on a 320x120 canvas, auto-fit font). Primary action cards gained
  an image picker (dropdown from library + thumbnail); secondaries can't
  have images per schema.
- Renderer: `_panel_image()` two-level cache (asset -> Surface, plus
  per-target-size smoothscale cache); image replaces the label inside the
  panel content area (panel minus status bar minus hint line — measured so
  nothing spills), aspect-fit + centered. Expression strip shows the active
  assignment's image fit to strip width. Labels now auto-fit via `_fit_text`
  everywhere (M13 "text must resize" requirement).
- Verified on the Pi: uploaded a generated PNG over the API, byte-identical
  round-trip via `/images/…`, assigned to Menu 1 B1 -> screenshot shows the
  image scaled inside the panel (fixed an overlap with the "Hold for" hint
  by shrinking the content box); delete cleared the reference and the user's
  config was restored. 122 unit tests passing.

### Milestone 13.5 — Hold UI (2026-07-06)
- `state.hold_started[num] = (pressed_at, hold_seconds)` while a hold action
  is arming: set by ActionLogic on press of a button WITH a secondary
  (buttons without one show no bar — they have no hold time), and by
  MenuLogic for Shift (as button 10, shift_hold_seconds). Cleared on
  release, on secondary/Menu-4 fire, and on the Shift+B5 combo.
- Renderer `hold_progress()` (pure, unit-tested): 0 for the first 0.2 s
  (HOLD_GROW_DELAY_S), then rescaled over (hold - 0.2) so the bar tops out
  exactly at the hold time; holds <= 0.2 s jump straight to full.
- `_draw_hold_bar`: light gray (#4E4E4E) fill growing upward from the panel
  bottom, drawn between the panel background and everything else (text,
  hint, status bar), rounded bottom corners.
- Verified on the Pi with a headless SDL-dummy render harness (physical
  buttons still unwired): injected B1 at 50% of its 1.5 s hold and Shift at
  50% of 2.0 s — screenshot shows both bars at exactly half height behind
  the content. 132 unit tests passing.

### Milestone 14 — BLE MIDI (2026-07-06)
- `midi/ble_codec.py`: pure BLE-MIDI packet codec (13-bit timestamps,
  running status incl. status-omitted and data-only forms, realtime bytes
  pass through without touching running status, sysex dropped). Unit-tested.
- `midi/ble.py BleMidiServer`: BLE MIDI peripheral over BlueZ D-Bus — GATT
  app (MIDI service 03B80E5A…/char 7772E5DB…, read + write-without-response
  + notify) + LE advertisement, GLib main loop in a daemon thread. Needs apt
  `python3-dbus python3-gi` (installed on the Pi; venv is
  --system-site-packages). Degrades to USB-only if dbus/adapter missing.
  Sends notify per message via GLib.idle_add (thread-safe); incoming
  WriteValue packets decode -> mido messages -> the same main event queue.
- **Kernel/BlueZ gotcha**: bluetoothd 5.82 registers ads with the EXTENDED
  advertising MGMT commands; kernel 6.18 returns Invalid Parameters for
  them on the Zero 2 W's legacy-only radio (btmon: Add Extended Advertising
  Data 0x0055 -> 0x0d). Fallback: `sudo -n btmgmt add-adv -c -g -u <MIDI
  UUID> 1` (legacy path works). btmgmt never exits/prints when piped, so
  it runs under `timeout 5` and success is confirmed via `bluetoothctl
  show` ActiveInstances. GATT connections still land on the bluetoothd app.
- Adapter prep on the Pi (persisted): `rfkill unblock bluetooth`, powered on
  via D-Bus at server start each boot, Alias set to device.name.
- MidiEngine reworked: USB and BLE transports side by side; outgoing goes to
  every enabled+connected transport (`midi.usb_enabled`/`ble_enabled` read
  LIVE at send time so the new Global Settings checkboxes mute immediately;
  enabling a transport that was off at boot needs a restart). `MIDI out
  (usb+ble): …` logging shows routing.
- Verified on the Pi: journal shows GATT registered + "advertising via
  btmgmt (legacy)", ActiveInstances 1, USB still open, settings toggles
  round-trip. NOT yet verified: an actual MainStage BLE connection (needs
  the user's Mac: Audio MIDI Setup -> Bluetooth -> connect "guitar-pedal"/
  "Pi MIDI Foot Controller"; a CoreBluetooth scan from the CLI was blocked
  by macOS Bluetooth TCC permissions). 142 unit tests passing.

### Post-M14 — editor UX tweaks (2026-07-06, user-directed)
- Card color fields no longer show the 10 palette swatches inline: a compact
  current-color button opens a popover with the palette in a 5x2 grid and a
  full-width "Choose color not on palette" button (opens the native color
  input -> unlinked custom color).
- Note numbers (effect_cc/action_cc) show their NOTE NAME next to the label,
  MainStage/Logic convention C3 = 60 (e.g. 66 -> F#3), live while typing;
  input stays numeric. "Use next available: N (name)" button now shows at
  ALL times (was only inside the duplicate warning).
- Palette slots gained LABELS: `ui.color_palette_labels` (10 strings, max 20
  chars, empty -> UI falls back to "Palette N"; back-filled on old configs/
  presets by _fill_missing, and included in preset files since presets
  snapshot the whole config). Edited on the Palette tab (label input under
  each color); the menu editor's color picker shows the label on the
  current-color button and in swatch tooltips. `/api/palette` now takes
  {colors?, labels?} and returns both.
- NOT yet verified in a browser — the Pi was powered off when this landed;
  JS syntax node-checked only. Deploy + click through on next power-up.

### Post-M14 — BLE advertising troubleshooting (2026-07-06)
- User report: pedal not visible in the Mac's Bluetooth settings. Root
  causes found with a CoreBluetooth scanner run from the Mac (works from a
  shell once Terminal has the Bluetooth permission):
  1. At boot the btmgmt fallback raced adapter power-up. Fix: the fallback
     now runs on a worker thread that waits for `bluetoothctl show`
     "Powered: yes" (up to 20 s) before rm-adv/add-adv.
  2. The old "ActiveInstances" success check was a FALSE NEGATIVE:
     bluetoothd never counts instances added via btmgmt (stays 0x00 even
     while the radio transmits — btmon shows LE Set Advertise Enable
     Success). Check removed; verify over the air instead.
  3. The advertisement had NO NAME (btmgmt's `-n` flag emits no scan
     response at all), so macOS had nothing to list it by. Fix: explicit
     `-s` scan-response bytes built from device.name (AD type 0x09 complete
     name, 0x08 shortened if truncated to the 31-byte budget).
- Verified from the Mac after a clean service restart: advertisement carries
  LocalName "Pi MIDI Foot Controller" + the MIDI service UUID.
- REMINDER for connecting: BLE MIDI peripherals do NOT appear in macOS
  System Settings -> Bluetooth. Use Audio MIDI Setup -> Window -> Show MIDI
  Studio -> Bluetooth button -> Connect.

### Milestone 15 — Settings Menu (2026-07-06)
- `hardware/sysinfo.py`: system status shell-outs with hard timeouts, all
  degrading to unknown values (Wi-Fi SSID via `iw dev wlan0 link`, IP via
  `hostname -I`, hostname, `bluetoothctl show` powered/discoverable, USB
  gadget UDC state from `/sys/class/udc/*/state`, pairing toggle =
  `bluetoothctl discoverable/pairable on|off`). `_run()` falls back to
  /usr/sbin and /usr/bin prefixes — `iw` is NOT on PATH over plain ssh.
- `logic/settings.py` rewritten: main view rows Wi-Fi / Bluetooth MIDI /
  USB MIDI / IP+hostname / Pairing mode (toggle) / Preset (opens preset
  view) / Exit. Status gathered on a worker thread every 2 s while open
  (never blocks the 10 ms loop); rows composed into `state.settings_rows`
  as (label, value) pairs so the renderer stays dumb. Selecting an info row
  forces an immediate refresh. Providers/presets/save are constructor-
  injectable; tests run the workers inline via `_spawn` override.
- Preset view: lists saved presets ("current" marker, selection starts on
  the active one), select = load (install_config + save_config, same swap
  semantics as the web path), Back row / B10 return to the main view
  (B10 only exits from the main view). Reopening always resets to main.
- `install_config` moved to `StateManager.install_config()` (web/server.py
  keeps a thin delegate) so on-device preset switching doesn't import web.
- MidiEngine gained `usb_open` and `ble_state` (off/advertising/connected)
  for the status rows; USB row combines UDC state ("host connected"/"no
  host") with whether the ALSA port is open.
- Renderer settings screen: title SETTINGS/PRESETS, label left + live value
  right per row, scroll window keeps the selection visible for long preset
  lists, 46 px rows so all 7 main rows fit 480 px, legend shows B10
  exit/back per view.
- Verified on the Pi: sysinfo live values (SSID "Hogwarts", IP, bluetooth
  flags, UDC "not attached"), pairing toggle round-trip
  (discoverable no->yes->no), headless screenshots of both views with real
  system data. Physical navigation still awaits wired buttons (Milestone 3).
- 151 unit tests passing.

### Milestone 16 — Polish and Reliability (2026-07-06)
- **Top header bar** (52 px, grid/expression strip moved below it): current
  patch on the left ("PATCH n · LABEL", label found from any program_change
  assignment matching the current program, base-aware), tempo + power status
  top right. Verified by live screenshot with the user's config.
- **Tempo**: `midi/tempo.py TempoTracker` (pure, unit-tested) computes BPM
  from incoming MIDI clock (24 ppqn, 2-beat window, >1 s gap resets).
  Handled on the MIDI input thread in the engine (48 pulses/s never touch
  the main queue); header shows "--- BPM" when the clock stops for 2 s.
  mido's rtmidi backend does deliver clock (ignore_types timing=False).
- **Battery**: `hardware/battery.py` stub returns None until the BMS
  milestone; header shows "AC" (renders "n% CHG" once read() returns data).
- **Render throttling**: the render thread computes a frame signature
  (state fields + config_version counter + coarse time buckets for
  flicker/tempo staleness) and skips draw + GL upload + flip when
  unchanged — the last flipped frame stays on scanout. Idle CPU dropped
  ~90% of a core -> ~9% total. Animations force redraws (signature None
  while hold bars run); hold frames tick at 60 fps target for a smoother
  bar. `state.config_version` is bumped by web mutations and
  install_config so config edits repaint immediately.
- **Reconnects**: MidiEngine.tick() reopens the USB gadget port every 5 s
  when closed (boot race or send failure — sends now close the port and
  let tick reopen; repeat failures log at DEBUG after the first). BLE:
  StopNotify re-arms the btmgmt legacy advertising instance (a legacy-path
  connection consumes it and bluetoothd only re-arms its own D-Bus ads) so
  the pedal reappears in scans after a central disconnects.
- **Error handling**: a _draw exception logs the traceback and shows a red
  "UI ERROR" screen instead of killing the render thread; the main loop
  wraps event dispatch + ticks so one bad event can't take the controller
  down mid-set.
- **Logging**: per-message MIDI in/out demoted to DEBUG (busy DAW sessions
  made the journal chatty); unit adds journal rate limiting.
- **systemd hardening**: Type=notify with `hardware/sdnotify.py` (READY=1,
  STOPPING=1, WATCHDOG=1 every 10 s from the main loop), WatchdogSec=30,
  Restart=always, StartLimitIntervalSec=0, After=bluetooth.service.
  Verified live: service active under Type=notify, NRestarts=0.
- **Power hold = real shutdown**: PowerLogic fires an injected on_shutdown
  (main.py -> `sudo -n systemctl poweroff`; None in tests so nothing real
  runs). systemd stops the service cleanly on the way down.
- State persistence assessment: config/preset writes were already atomic
  (tmp + rename); runtime state (menu, effect states) is intentionally
  ephemeral — it must resync from MIDI feedback after boot.
- 163 unit tests passing.
- NOT yet exercised live: tempo readout with a real MIDI clock source, BLE
  re-advertise after a central disconnect (no central has connected yet),
  UI error screen (unit-level only).

### Post-M16 — full Settings tab with preset/device scopes (2026-07-06)
- Web "Global Settings" tab became "Settings" and now exposes EVERY editable
  setting, split into two visually distinct groups:
  - **Preset settings** (saved into presets, travel with export/import):
    preset name, shift hold, default secondary hold, program display base,
    default MIDI channel (new), expression panel width, the four theme
    colors (new).
  - **Device settings** (this pedal only): device name (new), web port
    (new), USB/BLE transport toggles, button debounce / power double-press /
    power hold (new), expression hardware (detect pin, deadband, poll
    interval, home-return alpha/interval/stop threshold — all new).
    Hints mark which need a restart (most are cached at module init).
- Scope semantics enforced server-side via
  `config/defaults.py DEVICE_SETTING_PATHS` + strip/copy helpers:
  - preset save/export strips device keys from the file;
  - preset load/new/import overlays the live device settings onto the
    incoming config (web `_install` AND the on-device settings menu), so a
    preset — including one from another pedal — can never change device
    configuration. Undo/redo still snapshots the full config, so device
    edits remain undoable.
  - Legacy preset files that still contain device keys are neutralized by
    the same overlay on load.
- `/api/settings` validates the whole surface (table of new validators:
  _int/_string; theme colors are literal #RRGGBB only, no palette refs);
  client applies responses through a SETTING_PATHS map instead of ad-hoc
  key routing.
- Verified locally (Mac, temp CONFIG_DIR, real HTTP server): mixed
  preset+device settings post, 400 on bad web_port, export without device
  keys, load reverting preset values while keeping device values, page
  serving both groups. 173 unit tests passing.
- NOT deployed: the Pi was powered off when this landed. Deploy +
  browser click-through of the new Settings tab on next power-up.

### Post-M16 — boot screen (2026-07-06)
- `app/ui/assets/loading_screen.jpg` (user's 1920x480 artwork, moved from
  the repo root; the 96 MB `loading_screen.psd` source stays in the root,
  gitignored) drawn full-bleed while booting: last 4 startup messages
  bottom-left (drop-shadowed), firmware version bottom-right.
- `app/version.py FIRMWARE_VERSION` ("1.0.0") — bump per notable deploy;
  logged at startup too.
- `state.booting` + `state.boot_log()` (atomic list swap, render-thread
  safe); main.py logs config/MIDI/web/inputs/ready steps. Because startup
  finishes before the display even initializes, the renderer holds the
  boot screen for BOOT_MIN_SECONDS (2.5 s) after display-up, then the
  frame signature flips and the normal UI paints. Boot frames only repaint
  when a message arrives.
- Verified locally with a Mac scratch venv (pygame 2.6.1, SDL dummy):
  rendered boot frame shows artwork + messages + v1.0.0. NOT yet seen on
  the Pi (powered off) — verify on next power-up boot.

### Post-M16 — silent boot + early framebuffer splash (2026-07-06, PREPARED,
### not yet applied — Pi was off)
- Goal: artwork on screen for the whole Pi boot, terminal text never shown.
- `scripts/render-splash-fb.py`: pre-renders loading_screen.jpg into raw
  /dev/fb0 pixels (splash.fb) matching the live fb geometry from sysfs
  (32 bpp BGRX and 16 bpp RGB565 paths, stride padding). Tested locally
  against a fake sysfs at both depths incl. byte-exact round-trip.
- `systemd/boot-splash.service`: DefaultDependencies=no oneshot, polls for
  /dev/fb0 (vc4 loads a few seconds into boot) then cats splash.fb into it.
  Installed by deploy.sh; needs `systemctl enable` (setup script does it).
- `scripts/setup-boot-splash.sh` (run ON the Pi, idempotent, backs up
  cmdline.txt): adds quiet/loglevel=3/logo.nologo/vt.global_cursor_off=1,
  moves console tty1->tty3, disable_splash=1 in config.txt, renders
  splash.fb, enables boot-splash.service, disables getty@tty1.
- **TO APPLY on next power-up**: `./deploy.sh` then
  `ssh pedal 'bash /opt/midi-controller/scripts/setup-boot-splash.sh'`,
  reboot and watch: no rainbow, black -> artwork within a few seconds ->
  app boot screen (same artwork + messages) -> UI. Verify nothing regressed
  in the app itself. Revert notes are in the setup script header.

### Post-M16 — hold-bar framerate optimization (2026-07-06)
- Problem: while a hold bar animated, the frame signature went None and the
  renderer did a FULL redraw (all 10 panels, header, font renders) plus a
  `pygame.image.tobytes` convert+copy of the whole 1920x480 canvas every
  frame at a 60 fps target — too much for the Zero 2 W, choppy bar.
- Fix 1 — base-frame caching: `_frame_signature` no longer returns None on
  holds (it now describes the static BASE frame only); `_run` keeps the base
  on a cached surface, and each animation frame just blits it and redraws
  ONLY the held panels (`_draw_holds` -> `_draw_panel`, B10 factored into
  `_draw_shift_panel`; `_draw_hold_bar` takes a holds snapshot dict).
- Fix 2 — zero-copy GL upload: `_canvas_upload_mode()` inspects the canvas
  masks/pitch; when the layout is 4 bytes/pixel XRGB/XBGR with no row
  padding, the locked surface's `_pixels_address` goes straight to
  `glTexSubImage2D` and the gles fragment shader swizzles (.rgb/.bgr,
  `CanvasPresenter(swizzle=)`); unknown layouts fall back to tobytes("RGBA").
- Headless verification (Mac scratch venv, SDL dummy): composed frame is
  pixel-correct (bar heights at 50%/25%, content on top, pixels outside held
  panels identical to base); per-frame cost 1.80 ms -> 0.29 ms (6.2x) before
  even counting the removed GL-upload copy. Upload mode resolved to
  ("bgr", direct) on the dummy driver — same XRGB8888 expected on kmsdrm.
- 181 unit tests passing (new: upload-mode table; hold no longer dirties
  the signature).
- NOT yet deployed/verified on the Pi (deploy not part of the request):
  `./deploy.sh`, then hold B1 / Shift and watch the bar smoothness; check
  journal for no "draw failed" and idle CPU still low.

### Post-M16 — BLE "found but offline" root cause: btmgmt no-ops without a
### TTY (2026-07-06)
- Symptom: pedal listed but offline/unconnectable in the Mac's Audio MIDI
  Setup Bluetooth window; a CoreBluetooth scan from the Mac found NO
  advertisement at all.
- Root cause (btmon-confirmed): `btmgmt` run via subprocess WITHOUT a
  controlling terminal opens the MGMT socket and sends ZERO commands until
  timeout kills it. The app's legacy-advertising fallback has therefore
  never actually armed the radio from the service; every past success was
  from an interactive shell (tty). The "advertising via btmgmt (legacy)"
  log line was a false positive.
- Fix in `midi/ble.py _btmgmt()`: run under
  `sudo -n timeout 5 script -qec "btmgmt <args>" /dev/null` — the
  pseudo-TTY makes btmgmt execute, print, and exit promptly. Output is now
  returned and `_legacy_advertise` requires the literal "Instance added"
  confirmation before logging success (logs an error otherwise). 181 tests
  still pass.
- VERIFIED over the air from the Mac (CoreBluetooth test script in the
  session scratchpad): scan finds "Pi MIDI Foot Controller" with the MIDI
  service UUID, connect + service/char discovery + notify subscription all
  succeed — NO pairing required (adapter Pairable stayed off; the pairable
  toggle was tested and reverted). First-ever central connection: journal
  shows subscribe path works.
- Audio MIDI Setup note: a previously-seen device shows "Offline" until a
  fresh advertisement is received; it recovers by itself once advertising
  is really up.
- NOT DEPLOYED YET (deploy blocked in auto mode): `./deploy.sh` then check
  `journalctl -u midi-controller | grep -i ble` for "advertising via btmgmt"
  (real now), then connect from Audio MIDI Setup and play — also exercises
  the M16 re-advertise-after-disconnect path, which was equally broken by
  the tty bug and is fixed by the same change.

### Post-M16 — real 1920x480 panel reconfigured (2026-07-06)
- The desk-monitor debugging had left THREE `video=HDMI-A-1:1920x1080M@60D`
  entries in /boot/firmware/cmdline.txt (the M2 1920x480 forced mode was
  gone); the new physical panel's EDID advertises only bogus modes (max
  1024x768), so the app was rendering into a cropped 1024x768 fb.
- Fixed on the Pi: restored a single `video=HDMI-A-1:1920x480M@60D`
  (backup at cmdline.txt.bak-1080), rebooted. Verified: fb 1920,480,
  journal "display up: mode 1920x480", live screenshot shows the user's
  config full-bleed.
- splash.fb was still sized for 1024x768 — re-rendered via
  render-splash-fb.py (now 1920x480 @ 16 bpp). boot-splash.service is
  enabled (setup-boot-splash.sh HAS been applied; quiet/loglevel args
  present in cmdline).
- STILL PENDING: `./deploy.sh` (blocked in auto mode) carrying the hold-bar
  framerate optimization AND the btmgmt-TTY BLE advertising fix — until
  then the pedal is NOT advertising BLE after this reboot.

### Post-M16 — black screen root cause: production panel is PORTRAIT-scan
### (2026-07-06)
- After the 1920x480 forced mode was restored the panel showed NOTHING even
  though software looked healthy (CRTC active, screenshots fine). Fresh
  EDID after a reboot revealed why: the panel's ONLY real modes are
  portrait — preferred 480x1920@60 (pclk 66.28 MHz, tight blanking) plus a
  51 Hz variant. There is NO landscape mode; the forced 1920x480 CVT
  timings (`type: userdef` in modetest) can never sync. The earlier
  1024x768 EDID reading was bogus/stale (M2 gotcha).
- USER-CONFIRMED via modetest SMPTE pattern at mode #0 (480x1920): bars
  visible, rotated 90° — panel and cabling fine, native mode syncs.
- Fixes (LOCAL, NOT DEPLOYED — user chose to hold off):
  - cmdline.txt on the Pi: forced video= mode REMOVED (already applied on
    the device; kernel will pick the EDID-preferred 480x1920 on next
    reboot). Backups: cmdline.txt.bak (M2), .bak-1080 (desk-monitor era).
  - `hardware/constants.py DISPLAY_ROTATION_DEGREES = 90` (flip to 270 if a
    future panel batch comes up upside down).
  - `ui/renderer.py`: when no landscape mode fits the 1920x480 canvas, pick
    the smallest TRANSPOSED mode and pass rotation to the presenter; log
    line now includes rotation.
  - `ui/gles.py`: `CanvasPresenter(rotation=0|90|180|270)` — per-rotation
    UV table on the fullscreen quad + transposed viewport; canvas stays
    1920x480 everywhere (screenshots unaffected).
  - `scripts/render-splash-fb.py`: rotates the artwork CW when the fb is
    portrait (SPLASH_ROTATE_DEGREES overrides; must match the constant).
    Verified locally against a fake 480x1920 sysfs — preview correct.
- 181 unit tests passing.
- DEPLOYED AND VERIFIED (2026-07-06): user ran deploy.sh; first attempt
  still showed rotation 0° because the kernel STILL LISTED the old userdef
  1920x480 mode (cmdline is parsed at boot — removing the video= arg needs
  a reboot before the phantom mode disappears from the mode list). After
  reboot: fb 480,1920, journal "display up: mode 480x1920 ... rotation
  90°", BLE advertising armed with real btmgmt confirmation, splash.fb
  re-rendered at 480x1920 @ 16 bpp on the Pi. USER-CONFIRMED the panel
  shows the UI correct and readable. DISPLAY_ROTATION_DEGREES=90 is the
  right direction for this panel.

### Post-M16 — blank presets + secondary action_cc color duration (2026-07-09)
- Presets tab gained "Start blank preset": `/api/preset/new` accepts
  `blank: true` -> `new_preset_config(name, blank=True)` = default config
  with every menu's slots emptied (all buttons unassigned, all
  preset-scope settings at defaults; device settings overlaid as usual).
- action_cc SECONDARY actions gained `color_duration` (0.1-10 s, default
  1.0): how long the on_color shows after the hold fires. Replaces the
  old held-based display (`secondary_pressed`), which effectively flashed
  one frame because the fire happens mid-hold and release cleared it.
  ActionLogic opens `state.secondary_color_until[(menu, num)] = t + dur`
  on fire (pruned in tick); renderer checks the window (release does NOT
  close it) and the frame signature includes the active-window set so
  expiry repaints. `secondary_pressed` still suppresses the primary's
  pressed color. Web editor shows the field on secondary cards only
  (kind "secs": float input, step 0.1); server defaults missing values
  to 1.0 so old configs need no migration.
- 196 unit tests passing. NOT deployed (SSH to the Pi still broken).

### Post-M16 — external ACT LED on GPIO 20 + pin remap (2026-07-09)
- External LED on GPIO 20 becomes the Pi's onboard ACT LED itself: kernel
  device-tree remap (`dtparam=act_led_gpio=20` + `act_led_activelow=off`),
  applied by `scripts/setup-act-led.sh` (run on the Pi, reboot to take
  effect; onboard LED goes dark — the led node moves, it isn't mirrored).
  Assumes GPIO 20 -> resistor -> LED -> GND. `GPIO_LED_ACT = 20` recorded
  in constants; the app must never claim that pin.
- User pin remaps: power button 6 -> 21, B7 21 -> 6. B3 moved off 20 to
  PLACEHOLDER GPIO 25 (not wired yet — update constants when wired). All
  16 GPIO constants verified conflict-free.
- Script NOT yet run on the Pi (SSH still broken).

### Post-M16 — default expression assignment (2026-07-09, user-directed)
- Expression actions gained `is_default` (bool): the pot drives that
  assignment whenever NO expression button is selected
  (`state.expression_mode is None`). At most ONE default config-wide —
  saving a default clears the flag on every other expression assignment
  (`web/server.py _enforce_single_default_expression`, inside the same
  undo snapshot).
- `StateManager.effective_expression_mode()` = selected mode or the
  default (found via `config/model.py find_default_expression`, cached by
  config_version); `get_expression_action()`, the renderer's expression
  active-color check, and `/api/status` all use it, so the default slot
  lights up and the strip shows its assignment with nothing selected.
  Home-return on switch-away works for the default too (set_mode reads
  "previous" through the same fallback).
- Web editor: "Default expression" checkbox in the expression field list
  (primary and secondary); saving a default refetches the config so other
  cards' cleared checkboxes update. Old configs need no migration
  (`.get("is_default")` is falsy when absent).
- 192 unit tests passing. NOT yet deployed — SSH key auth to the Pi is
  broken (Pi rejects both Mac keys; needs `ssh-copy-id` with a password
  first), which also blocks the pending deploys listed below.

## Current Milestone

All roadmap milestones through 16 complete. Next up: user hardware bring-up
(button wiring, pot, BLE connection from MainStage) and the future
battery/BMS milestone.

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

1. User verification pending: connect MainStage over BLE (Audio MIDI Setup ->
   Bluetooth) — advertising is live but an actual central connection hasn't
   been exercised. That will also exercise the M16 BLE re-advertise path and
   the tempo header (MainStage sends MIDI clock).
2. Still pending from earlier: physical button wiring (Milestone 3) and pot
   hardware (Milestone 5) bench verification; hold-bar UI (13.5), settings
   menu navigation (15) and power-hold shutdown (16) get their first real
   exercise then.
3. Deploy pending (Pi was off): post-M16 Settings tab (preset/device scopes).
   Also still unverified in a real browser: post-M14 palette labels/popover
   and the new Settings tab click-through.
4. Future milestone: battery/BMS (hardware/battery.py read() is the hook).
