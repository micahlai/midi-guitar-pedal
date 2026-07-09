"""Central definition of every GPIO/SPI assignment (BCM numbering).

All hardware pin numbers live here and nowhere else. Numbers follow the
draft in docs/02_HARDWARE_SPEC.md and may change once wiring is finalized.

Physical layout:
    TOP ROW:    B1  B2  B3  B4  B5
    BOTTOM ROW: B6  B7  B8  B9  B10 (Shift/Menu, not assignable)
"""

GPIO_BUTTON_1 = 3
GPIO_BUTTON_2 = 4
GPIO_BUTTON_3 = 17
GPIO_BUTTON_4 = 27
GPIO_BUTTON_5 = 22
GPIO_BUTTON_6 = 5
GPIO_BUTTON_7 = 6
GPIO_BUTTON_8 = 13
GPIO_BUTTON_9 = 19
GPIO_BUTTON_10_SHIFT = 26

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

# Physical button number (B1-B10) -> BCM pin.
GPIO_BY_BUTTON = {
    1: GPIO_BUTTON_1,
    2: GPIO_BUTTON_2,
    3: GPIO_BUTTON_3,
    4: GPIO_BUTTON_4,
    5: GPIO_BUTTON_5,
    6: GPIO_BUTTON_6,
    7: GPIO_BUTTON_7,
    8: GPIO_BUTTON_8,
    9: GPIO_BUTTON_9,
    10: GPIO_BUTTON_10_SHIFT,
}

# External LED remapped to be the onboard ACT LED itself (kernel-driven via
# dtparam=act_led_gpio=20 in config.txt — scripts/setup-act-led.sh). The app
# must never claim this pin.
GPIO_LED_ACT = 20

GPIO_POWER_BUTTON = 21
# Event-stream button number for the power button (footswitches are 1-10).
BUTTON_NUM_POWER = 0

# Moved from draft GPIO 23 (now B5). Low = pedal plugged in (jack switch to
# GND, internal pull-up).
GPIO_EXPRESSION_DETECT = 2

# MCP3008 ADC on SPI0. Pins are fixed by the SPI0 hardware block and driven
# by the kernel spidev driver, not GPIO'd directly.
GPIO_SPI0_MOSI = 10  # MCP3008 DIN
GPIO_SPI0_MISO = 9   # MCP3008 DOUT
GPIO_SPI0_SCLK = 11  # MCP3008 CLK

SPI_ADC_BUS = 0
SPI_ADC_DEVICE = 0  # CE0 (GPIO 8) -> MCP3008 CS
SPI_ADC_CHANNEL_POT = 7

# Buttons wired between GPIO and GND with internal pull-ups: pressed reads low.
BUTTON_ACTIVE_LOW = True

DISPLAY_WIDTH = 1920
DISPLAY_HEIGHT = 480
# The production panel is a portrait-scan TCON (EDID preferred mode is
# 480x1920, no landscape mode at all): the renderer drives it at native
# portrait and the GL presenter rotates the landscape canvas by this many
# degrees clockwise. Flip to 270 if the image comes up upside down on a
# different panel batch. Only used when no landscape mode fits the canvas.
DISPLAY_ROTATION_DEGREES = 90
