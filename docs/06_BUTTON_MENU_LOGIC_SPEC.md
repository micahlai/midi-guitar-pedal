# Button and Menu Logic Specification

## Physical Button Layout

```text
B1   B2   B3   B4   B5
B6   B7   B8   B9   B10
```

Special:
- B10 = Shift/Menu button.
- B5 = assignable normally.
- Shift + B5 opens Menu 3.

## Menus

There are 4 menus:
- Menu 1
- Menu 2
- Menu 3
- Menu 4

Each menu has 9 assignable button slots:
- B1-B9

Total assignable slots:
- 4 menus × 9 buttons = 36 primary actions

Total possible actions:
- 36 primary + 36 secondary = 72 max

## Shift Behavior

### Press Shift
Pressing B10 switches between Menu 1 and Menu 2.

Recommended precise behavior:
- Short press/release of B10 toggles Menu 1 <-> Menu 2.
- If currently on Menu 3 or Menu 4, short press returns to Menu 1 or toggles according to defined UX.
- Make this behavior configurable later if needed.

### Shift + Top Right
When B10 is held and B5 is pressed:
- open Menu 3
- do not trigger B5's normal assignment
- do not send B5's primary MIDI action

### Shift Hold
Holding B10 for Shift Hold Duration opens Menu 4.
Default:
- `2.0 seconds`

Configurable:
- web app setting

## Button Press Timing

Every assignable button may have:
- primary action
- optional secondary hold action

If no secondary action:
- primary action may fire on initial press.

If secondary action exists:
- primary action must wait until release.
- if button is released before hold threshold: primary action fires.
- if button is held beyond threshold: secondary action fires.
- after secondary fires, releasing button should not fire primary.

Default secondary hold threshold:
- `1.5 seconds`

Per-button configurable.

## Debounce

All physical buttons must be debounced.

Recommended:
- debounce interval: 20-40 ms
- constants in config/hardware file

## Button State Events

Use event model:
- pressed
- released
- held threshold reached
- double press only for power button
