#!/usr/bin/env bash
# Remap the Pi's onboard ACT LED to the external LED on GPIO 20. Run ON the
# Pi (deploy.sh syncs this to /opt/midi-controller/scripts/). Idempotent;
# takes effect after a reboot.
#
#   ssh pedal 'bash /opt/midi-controller/scripts/setup-act-led.sh'
#
# The kernel then drives GPIO 20 with the exact onboard ACT LED behavior
# (same led node, same trigger); the onboard LED itself goes dark since the
# led is moved, not mirrored. Wiring assumption: GPIO 20 -> resistor ->
# LED -> GND (active-high; the onboard LED is active-low, hence the
# activelow=off override).
#
# Revert: delete both dtparam lines from /boot/firmware/config.txt, reboot.
set -euo pipefail

CONFIG=/boot/firmware/config.txt
GPIO=20

for param in "act_led_gpio=$GPIO" "act_led_activelow=off"; do
  if grep -q "^dtparam=$param\$" "$CONFIG"; then
    echo "already set: dtparam=$param"
  else
    echo "dtparam=$param" | sudo tee -a "$CONFIG" >/dev/null
    echo "added: dtparam=$param"
  fi
done

# Catch a conflicting earlier remap to a different pin.
if grep "^dtparam=act_led_gpio=" "$CONFIG" | grep -vq "=$GPIO\$"; then
  echo "WARNING: another act_led_gpio line exists in $CONFIG — remove it:"
  grep -n "^dtparam=act_led_gpio=" "$CONFIG"
fi

echo "done — reboot to apply (sudo reboot)"
