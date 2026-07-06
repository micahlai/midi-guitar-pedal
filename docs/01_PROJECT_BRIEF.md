# Project Brief

## Product

A Raspberry Pi Zero 2 W based MIDI foot controller for guitar rigs, especially MainStage.

The controller has:
- 10 momentary push buttons / footswitches.
- One 1920×480 HDMI screen.
- One SPI ADC reading a potentiometer.
- One momentary power button.
- USB-C wired connection to a computer.
- Bluetooth MIDI connection option.
- Web configuration interface over Wi-Fi/network.

## Purpose

The controller should behave like a premium programmable MIDI pedalboard:
- Send MIDI Control Change messages.
- Send MIDI Program Change messages.
- Receive MIDI feedback from MainStage/DAW.
- Reflect effect state and current patch on the display.
- Allow user configuration through a browser-based web app.
- Save all mappings and UI settings locally.

## Fixed Hardware Assumptions

These should be treated as permanent:
- Display resolution: `1920x480`
- Button count: `10`
- Button layout: `5 columns x 2 rows`
- Potentiometer/analog input: `1`
- ADC transport: `SPI`
- Power button: `1 momentary`
- Main computer: `Raspberry Pi Zero 2 W`
- OS: `Raspberry Pi OS Lite`

## Main Interaction Model

The screen is divided into:
- A 5×2 button panel grid.
- A skinny right vertical section for potentiometer/expression display when active/present.

The bottom-right physical button is the shift/menu button. It is not assignable.

Assignable buttons:
- 9 assignable physical button positions per menu.
- 4 menus.
- 36 primary assignable button slots.
- Optional secondary/hold action for every assignable slot.
- 36 possible secondary actions.
- Maximum 72 possible configured actions.

## Menu Behavior

There are four menus:

### Menu 1
Default menu.

### Menu 2
Press the bottom-right Shift button to toggle/switch between Menu 1 and Menu 2.

### Menu 3
Press Shift, then press the top-right button to open Menu 3.

Important:
- The top-right button is a normal assignable button when not used with Shift.
- The Shift + top-right combo is reserved for entering Menu 3.

### Menu 4
Hold the Shift button for the configured duration to open Menu 4.
Default Shift hold duration:
- `2.0 seconds`
Configurable in web app.

## Power Button Behavior

Power button:
- Hold down: turn device on or off.
- Double press: open on-device settings menu.
- Settings menu mainly controls wireless/network settings.
- Settings menu is navigated using the 10 momentary pushbuttons.
- User can exit settings menu using buttons.

## Development

Development will happen over SSH on Raspberry Pi OS Lite.

Avoid assumptions that require a desktop Raspberry Pi OS install. The UI should run as a fullscreen framebuffer/DRM/SDL/Pygame/Qt app launched by systemd.
