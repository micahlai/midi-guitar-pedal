"""Central definition of every GPIO/SPI assignment (BCM numbering).

All hardware pin numbers live here and nowhere else. Numbers follow the
draft in docs/02_HARDWARE_SPEC.md and may change once wiring is finalized.

Physical layout:
    TOP ROW:    B1  B2  B3  B4  B5
    BOTTOM ROW: B6  B7  B8  B9  B10 (Shift/Menu, not assignable)
"""

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

# B1-B9 in physical order; B10 is Shift/Menu and never assignable.
GPIO_ASSIGNABLE_BUTTONS = (
    GPIO_BUTTON_1,
    GPIO_BUTTON_2,
    GPIO_BUTTON_3,
    GPIO_BUTTON_4,
    GPIO_BUTTON_5,
    GPIO_BUTTON_6,
    GPIO_BUTTON_7,
    GPIO_BUTTON_8,
    GPIO_BUTTON_9,
)

GPIO_POWER_BUTTON = 24
GPIO_EXPRESSION_DETECT = 23

SPI_ADC_BUS = 0
SPI_ADC_DEVICE = 0
SPI_ADC_CHANNEL_POT = 0

# Buttons wired between GPIO and GND with internal pull-ups: pressed reads low.
BUTTON_ACTIVE_LOW = True

DISPLAY_WIDTH = 1920
DISPLAY_HEIGHT = 480
