# Controller UI Specification

## Display

Resolution:
- Width: `1920 px`
- Height: `480 px`

The UI must be optimized for this exact wide aspect ratio.

## Main Layout

Default layout contains:
- 5 columns x 2 rows of button panels.
- Optional right-side vertical expression/potentiometer panel.

When expression panel is visible:
```text
┌──────────────────────────────────────────────┬────────┐
│ B1 │ B2 │ B3 │ B4 │ B5                       │ EXP    │
├────┼────┼────┼────┼────                      │ BAR    │
│ B6 │ B7 │ B8 │ B9 │ B10                      │        │
└──────────────────────────────────────────────┴────────┘
```

When expression panel is hidden:
```text
┌──────────────────────────────────────────────┐
│ B1 │ B2 │ B3 │ B4 │ B5                       │
├────┼────┼────┼────┼────                      │
│ B6 │ B7 │ B8 │ B9 │ B10                      │
└──────────────────────────────────────────────┘
```

## Button Panel Contents

Each assignable button panel should show:
1. Main label text OR low-resolution image.
2. Optional secondary-action hint text:
   - `Hold for _____`
3. Bottom colored status rectangle.

The bottom status rectangle is required for every visible assignable panel.

## Shift Button Panel

Bottom-right B10 is the Shift/Menu button.

Its panel should show menu/shift state, not user assignment.

It should visually indicate:
- current menu
- when Shift is pressed
- when Shift hold timer is active for Menu 4

## Status Bar Behavior

### Effect CC
Status bar color reflects current stored effect status:
- Off color when value is considered off.
- On color when value is considered on.

The status is updated by incoming matching CC values from DAW/MainStage.

### Action CC
Status bar color reflects physical press state only:
- Color A by default.
- Color B while currently pressed.
- It does not wait for or listen to MIDI feedback.

### Program Change
Status bar color reflects whether global current program number equals this button's assigned program:
- Color A if not current.
- Color B if current.

### Expression Pedal Type
Status bar color uses configured expression color when the expression mode is active.
Details in `08_EXPRESSION_PEDAL_SPEC.md`.

### Nothing
Show disabled/blank state.
Could use transparent/dim/default color.

## Menu Indicator

The UI should always show the current menu in a clear way:
- Menu 1
- Menu 2
- Menu 3
- Menu 4

This could be in the Shift panel or as a small global header.

## Settings Menu UI

Double pressing the power button opens the settings menu.

Settings menu focuses on:
- Wi-Fi/network status
- Bluetooth MIDI status
- USB MIDI status
- IP address / hostname
- Pairing mode
- Exit

Navigation:
- Use the 10 pushbuttons.
- Provide clear on-screen button labels for navigation.
- Must be usable without keyboard/mouse.
