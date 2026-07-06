# Roadmap and Milestones

## Milestone 1 — Raspberry Pi OS Lite Setup

Goals:
- Install Raspberry Pi OS Lite.
- Enable SSH.
- Configure Python environment.
- Create project directory.
- Create systemd service placeholder.

Deliverables:
- App starts on boot and logs to journal.
- `hello controller` or basic log loop.

## Milestone 2 — Display Bring-Up

Goals:
- Configure 1920x480 HDMI output.
- Launch fullscreen UI.
- Draw basic 5x2 layout.
- Draw right expression strip placeholder.

Deliverables:
- 1920x480 UI fills screen.
- Button grid visible.

## Milestone 3 — GPIO Buttons

Goals:
- Read 10 momentary buttons.
- Debounce buttons.
- Implement event model: press, release, hold.
- Implement Shift/Menu behavior.

Deliverables:
- Button presses logged.
- Shift toggles Menu 1/2.
- Shift + top-right opens Menu 3.
- Shift hold opens Menu 4.

## Milestone 4 — Power Button UI Behavior

Goals:
- Read power button GPIO.
- Detect double press.
- Open settings menu on double press.
- Stub hold shutdown behavior.

Deliverables:
- Settings menu opens and can be exited using footswitches.

## Milestone 5 — SPI ADC Potentiometer

Goals:
- Read SPI ADC.
- Normalize potentiometer value.
- Add expression detect pin.
- Display expression bar when detected.

Deliverables:
- Pot movement shown on screen.
- Expression panel hides when not detected.

## Milestone 6 — Config Data Model

Goals:
- Define JSON schema.
- Load defaults.
- Save config.
- Represent 4 menus x 9 assignable buttons.
- Represent primary/secondary actions.

Deliverables:
- Editable JSON file controls UI labels/colors.

## Milestone 7 — Basic MIDI Send

Goals:
- Set up USB MIDI.
- Send CC.
- Send Program Change.
- Map configured buttons to outgoing MIDI.

Deliverables:
- MainStage/DAW receives messages.

## Milestone 8 — MIDI Receive and State Sync

Goals:
- Receive CC.
- Receive Program Change.
- Update effect states from matching CC feedback.
- Update global current program from incoming PC.

Deliverables:
- UI status bars change from incoming MIDI.

## Milestone 9 — Action Types

Goals:
- Implement Effect CC.
- Implement Action CC.
- Implement Program Change.
- Implement Nothing.
- Implement Expression Pedal Type.

Deliverables:
- All primary action types work.

## Milestone 10 — Secondary Hold Actions

Goals:
- Add optional secondary action per button.
- Primary waits until release when secondary exists.
- Secondary fires after hold threshold.
- UI shows `Hold for _____`.

Deliverables:
- 72-action model works in theory.

## Milestone 11 — Web App Basics

Goals:
- Start local web server.
- Show four menu tabs.
- Show 9 assignable buttons.
- Edit primary action type.
- Save to config.

Deliverables:
- Browser can edit a button and controller updates.

## Milestone 12 — Full Web App Editor

Goals:
- Add all fields for action types.
- Add secondary action tab system.
- Add remove secondary action button.
- Add expression settings sidebar.
- Add shift hold duration setting.
- Add expression panel width setting.

Deliverables:
- Web app fully configures all core behavior.

## Milestone 12.5 - Web App Editor Additions

- Color palette (when picking a color, it'll first show the color palette (with 10 slots). Color palette can be edited on its own tab. these colors are linked to each other. When changing it in the color palette editor, it will change all of the colors with that slot). Users can also have the option to just pick another color (that isn't part of the color palette and be unlinked)
- Be able to label the menus. On display will say ($MENU NAME and menu # below it in the "hold for ___" font)
- Add warnings for duplicate program and cc notes but don't prevent it. Message should say on both duplicates "Warning: ## is used for ____ (the name of the other one). For action cc and effect cc, have button to use the next available note.
- JSON save and load (with preset names)
- Be able to upload multiple presets onto the device. Add another tab for preset load. Have option to start completely new preset. Preset name in global settings
- Undo/redo (restarting the device will reset the memory)

## Milestone 13 — Image Upload

Goals:
- In addition to label, be able to upload low-resolution images.
- Compress, resize/store images.
- Use images in button panels.
- Image creator on web app (just font and text; flatten as image)
- Support images for expression pedal type.
- Ensure images stay within the button panel on the display (including text which needs to resize font if necceasry)
- Display should show image but it is purely visual. Everywhere else should refer to the specific control by its label still

Deliverables:
- User can upload image and see it on controller screen.

## Milestone 13.5 - Hold UI
Goals:
- on display, have the a light gray rectangle (behind text and color) that grows vertically upward like a progress bar if that button is being held down. the grow time should represent the hold time. this should apply to menu shift key too. only start growing 0.2 seconds after the button has been held (recscale the time appropriately to account for this time change so it still reaches the top at the exact hold time)

## Milestone 14 — BLE MIDI

Goals:
- Advertise Bluetooth LE MIDI.
- Send MIDI over BLE.
- Receive MIDI over BLE.
- Allow choosing/using USB, BLE, or both.

Deliverables:
- MainStage can connect wirelessly.

## Milestone 15 — Settings Menu

Goals:
- On-device wireless settings menu.
- Show Wi-Fi/Bluetooth status.
- Pairing mode toggle.
- Show IP/hostname.
- Switch between loaded presets (from milestone 12.5)
- Exit to controller UI.

Deliverables:
- No web app needed for basic wireless status/actions.

## Milestone 16 — Polish and Reliability

Goals:
- Better rendering.
- Better state persistence.
- Display current patch on top of display as well as tempo and battery/charging status in top right
- Handle reconnects.
- Error screens.
- Logging.
- Crash recovery.
- systemd hardening.

Deliverables:
- Controller feels reliable enough for rehearsal.

## Future Milestone — Battery/BMS

Goals:
- Add battery status monitor.
- Add low battery UI warning.
- Trigger safe shutdown.
- Integrate with power hardware.
