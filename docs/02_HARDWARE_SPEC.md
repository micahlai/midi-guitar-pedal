# Hardware Specification

## Fixed Hardware

### Compute
- Raspberry Pi Zero 2 W

### Display
- HDMI display
- Resolution: `1920x480`
- UI must be designed specifically for this resolution.

### Buttons
- 10 momentary push buttons / footswitches.
- Direct GPIO inputs are acceptable.
- No GPIO expander required unless added later.
- Each button should use internal pull-up or pull-down consistently.
- Recommended wiring: button between GPIO and GND, internal pull-up enabled.

### Power Button
- 1 momentary power button.
- Behavior:
  - Hold: power on/off.
  - Double press while running: open settings menu.
- Software should expose constants for power button GPIO.
- Hardware may later include power management circuitry.
- Do not assume battery is present in v1.

### Potentiometer / Expression ADC
- One potentiometer is connected through an SPI ADC.
- The Pi has no built-in analog input, so all analog reads come from the SPI ADC.
- SPI bus and chip select must be constants.

### Expression Detect Pin
- There is a GPIO pin used to detect whether expression pedal/potentiometer input is considered plugged in/active.
- If not plugged in/active, the expression bar should not be shown and the 10 button panels resize to use the available width.

## Required GPIO Constants

Create a single hardware constants module/file.

Example names:

```python
GPIO_BUTTON_1 = 5
GPIO_BUTTON_2 = 6
GPIO_BUTTON_3 = 13
GPIO_BUTTON_4 = 19
GPIO_BUTTON_5 = 26
GPIO_BUTTON_6 = 12
GPIO_BUTTON_7 = 16
GPIO_BUTTON_8 = 20
GPIO_BUTTON_9 = 21
GPIO_BUTTON_10_SHIFT = 25

GPIO_POWER_BUTTON = 24
GPIO_EXPRESSION_DETECT = 23

SPI_ADC_BUS = 0
SPI_ADC_DEVICE = 0
SPI_ADC_CHANNEL_POT = 0
```

The exact pin numbers can change, but the codebase must clearly centralize them.

## Physical Button Layout

Numbering:

```text
TOP ROW:
B1   B2   B3   B4   B5

BOTTOM ROW:
B6   B7   B8   B9   B10
```

Special positions:
- `B10` bottom-right = Shift/Menu button.
- `B5` top-right = normal assignable button, but Shift + B5 opens Menu 3.

Assignable physical buttons:
- B1, B2, B3, B4, B5, B6, B7, B8, B9
- B10 is not assignable.

## Future Battery/BMS Add

Future hardware may add:
- Battery
- BMS
- Battery voltage measurement
- Low battery detection
- Safe shutdown

Software should be designed so a future battery monitor module can:
- read battery status
- notify UI
- trigger safe shutdown on low battery.
