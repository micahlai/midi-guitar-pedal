# Expression Pedal / Potentiometer Specification

## Hardware

A potentiometer is read through an SPI ADC.

There is also an expression detect GPIO pin.

If expression pedal/pot is detected:
- show right-side vertical bar
- show active expression label/image
- use configured display width

If not detected:
- hide right-side vertical bar
- resize 10 button panels to use full display width

## Expression Mode Source

The current expression behavior is determined by whichever button of type `Expression Pedal Type` is selected.

Examples:
- Volume
- Pitch
- Wah

## Expression Pedal Type Settings

Fields:
- MIDI channel
- CC code/number
- Label text OR low-resolution image
- Hex color
- Value map min integer
- Value map max integer
- Reverse boolean
- Has home value boolean
- Home value integer, only active if has home value is true

Defaults:
- Value map min: `0`
- Value map max: `127`
- Reverse: `false`
- Has home value: `false`

## Value Mapping

Raw ADC value should be normalized from 0.0 to 1.0.

If `reverse == false`:
- pedal down / max raw direction maps to configured max
- pedal up / min raw direction maps to configured min

If `reverse == true`:
- mapping is inverted.

Final MIDI value:
- integer 0-127 after mapping
- clamp to 0-127

## Expression Display Without Home Value

If no home value:
- show vertical bar from bottom when reverse is false
- show vertical bar from top when reverse is true

## Expression Display With Home Value

If home value exists:
- show home value as a line on the vertical bar
- render current value as distance from home value
- visual should communicate how far from home the expression currently is

## Home Value Return Behavior

If current expression mode has a home value and that expression pedal type is not selected:
- exponentially send CC messages to return the value back to its home value.

Meaning:
- if current value is far from home, move faster
- as current value gets close to home, move slower
- stop when value is close enough to home

Suggested algorithm:
- Keep current_sent_value as float.
- Every tick:
  - delta = home_value - current_sent_value
  - step = delta * RETURN_ALPHA
  - current_sent_value += step
  - send rounded MIDI CC if rounded value changed
- Stop when abs(delta) < threshold.

Constants:
```python
EXPRESSION_RETURN_ALPHA = 0.15
EXPRESSION_RETURN_INTERVAL_MS = 30
EXPRESSION_RETURN_STOP_THRESHOLD = 0.5
```

## MIDI Sending

When active:
- Pot movement sends configured CC.
- Use smoothing/deadband to avoid spamming MIDI.

Suggested:
```python
EXPRESSION_SEND_DEADBAND = 1
EXPRESSION_POLL_INTERVAL_MS = 10
```
