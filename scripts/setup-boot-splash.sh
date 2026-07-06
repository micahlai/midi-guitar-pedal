#!/usr/bin/env bash
# Silent boot + early splash screen. Run ON the Pi (deploy.sh syncs this to
# /opt/midi-controller/scripts/), after a deploy that installed
# boot-splash.service. Idempotent; backs up cmdline.txt first.
#
#   ssh pedal 'bash /opt/midi-controller/scripts/setup-boot-splash.sh'
#
# What it does:
#   1. cmdline.txt: quiet loglevel=3 logo.nologo vt.global_cursor_off=1,
#      console text moved from tty1 to tty3 (kernel/systemd messages never
#      touch the panel; switch VTs or use the journal to read them).
#   2. config.txt: disable_splash=1 (no firmware rainbow flash).
#   3. Pre-renders loading_screen.jpg into raw fb pixels (splash.fb).
#   4. Enables boot-splash.service (cat splash.fb > /dev/fb0 as soon as the
#      framebuffer exists).
#   5. Disables the tty1 login prompt (access is ssh; re-enable with
#      `sudo systemctl enable getty@tty1`).
#
# Revert: restore /boot/firmware/cmdline.txt.bak-splash, remove
# disable_splash=1, `systemctl disable boot-splash getty@tty1 --now` inverse.
set -euo pipefail

CMDLINE=/boot/firmware/cmdline.txt
CONFIG=/boot/firmware/config.txt
VENV=/opt/midi-controller/venv

echo "== 1/5 cmdline.txt"
sudo cp "$CMDLINE" "$CMDLINE.bak-splash"
line="$(tr -d '\n' < "$CMDLINE")"
line="${line//console=tty1/console=tty3}"
for param in console=tty3 quiet loglevel=3 logo.nologo vt.global_cursor_off=1; do
  case " $line " in *" $param "*) ;; *) line="$line $param" ;; esac
done
echo "$line" | sudo tee "$CMDLINE" >/dev/null
echo "   $line"

echo "== 2/5 config.txt: disable_splash"
grep -q '^disable_splash=1' "$CONFIG" || echo 'disable_splash=1' | sudo tee -a "$CONFIG" >/dev/null

echo "== 3/5 pre-render splash.fb from the framebuffer geometry"
sudo mkdir -p /opt/midi-controller/assets
sudo -E "$VENV/bin/python" /opt/midi-controller/scripts/render-splash-fb.py

echo "== 4/5 enable boot-splash.service"
sudo systemctl daemon-reload
sudo systemctl enable boot-splash.service

echo "== 5/5 disable the tty1 login prompt"
sudo systemctl disable getty@tty1.service

echo "done — reboot to see the silent boot + splash"
