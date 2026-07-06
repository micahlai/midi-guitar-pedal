# MIDI Specification

## Transports

The controller must support:
- USB MIDI over USB-C
- Bluetooth LE MIDI

It must send and receive MIDI over both where possible.

## Bidirectional MIDI Philosophy

The DAW/MainStage is expected to echo/return feedback for:
- CC messages
- Program Change messages

The controller should use returned MIDI messages to update internal state and display state.

This means:
- Do not assume that a button press itself confirms effect state.
- For Effect CC, the returned MIDI message is the source of truth.
- For Program Change, incoming program changes update the global current program, even if the patch changed from another device or the computer UI.

## Incoming MIDI Handling

The system should listen for:
- Control Change
- Program Change
- Optional Note messages in future

### Control Change Receive
When a CC is received:
1. Identify all button assignments of type Effect CC using that CC code/channel.
2. Update their stored effect status based on received value.
3. Refresh UI status bars.

Default status interpretation:
- value `0` = off
- value `1-127` = on

This can be enhanced later with thresholds.

### Program Change Receive
When a Program Change is received:
1. Store the global current program number.
2. Refresh all Program Change button panels.
3. Program buttons where assigned program equals current program show active color.

## Outgoing MIDI Handling

### Effect CC
On button action:
- Send configured CC number/channel/value.
- Then wait for incoming feedback to update state.

For first version:
- send value 127 on press.
- Later support toggle mode if needed.

### Action CC
On press:
- Send configured CC.
- Status color changes only while the button is physically held.
- Do not listen for feedback for this assignment.

### Program Change
On press:
- Send configured Program Change number.
- Global current program updates only when Program Change is received back.
- Optional optimistic UI update may be added later, but default should trust returned MIDI.

## MIDI Code Representation

User may refer to CC as musical-style codes like:
- `F#3`
- `G#5`
- `C#1`

The application must either:
1. Support this notation directly, converting to MIDI numbers, or
2. Clearly provide both note-style label and numeric MIDI value in the UI.

Internally, store MIDI values as numeric:
- Channel: 1-16
- CC number: 0-127
- Program number: 0-127 or 1-128 display-mapped

Be explicit about 0-based vs 1-based program display.
Recommended:
- Store PC internally as 0-127.
- Display to user as 1-128 if chosen in settings.
