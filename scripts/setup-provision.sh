#!/usr/bin/env bash
# One-shot provisioning for a FRESH Raspberry Pi OS Lite (32-bit, trixie)
# card: everything the app needs that the image does not ship. Run ON the Pi.
# Idempotent — safe to re-run.
#
#   ssh pedal 'bash /opt/midi-controller/scripts/setup-provision.sh'
#
# Written after a card rebuild where two of these were the difference between
# a working pedal and a black screen with no Bluetooth, and neither was
# recorded anywhere:
#
#   * Lite ships NO GL userspace at all, so ui/gles.py dies with "EGL not
#     initialized" and the panel stays black. libegl1/libgles2 fix it.
#   * BlueZ needs Experimental=true or GATT registration times out with a
#     D-Bus NoReply and BLE MIDI registers no service (advertising alone is
#     not enough — the notes ride on GATT).
#
# Still needed after this, in order:
#   config.txt: dtparam=spi=on, dtoverlay=dwc2,dr_mode=otg  (under [all])
#   ./deploy.sh
#   setup-act-led.sh, setup-boot-splash.sh
#   sudo systemctl enable midi-controller usb-midi-gadget
set -euo pipefail

VENV=/opt/midi-controller/venv

echo "== 1/4 apt packages"
sudo apt-get update -qq
sudo apt-get install -y -qq \
    python3-venv rsync \
    python3-pygame python3-mido python3-rtmidi \
    python3-dbus python3-gi \
    libegl1 libgles2 libegl-mesa0 libgbm1 \
    bluez bluez-tools rfkill

echo "== 2/4 venv (--system-site-packages: every dep above is an apt package)"
# Run as the pedal user, NOT with sudo: under sudo $USER is root, so the chown
# below would hand /opt/midi-controller to root — and every later deploy would
# then fail its rsync (and, with set -e, silently skip installing the systemd
# units). SUDO_USER keeps it correct either way.
OWNER="${SUDO_USER:-$USER}"
sudo mkdir -p /opt/midi-controller/{app,config,assets/images,scripts}
sudo chown -R "$OWNER:$OWNER" /opt/midi-controller
[ -d "$VENV" ] || python3 -m venv --system-site-packages "$VENV"
"$VENV/bin/python" - <<'PY'
import dbus, gi, mido, pygame, rtmidi  # noqa: F401
print("   imports OK — pygame", pygame.version.ver)
PY

echo "== 3/4 BlueZ experimental (GATT registration needs it)"
if ! grep -qE '^Experimental *= *true' /etc/bluetooth/main.conf; then
    sudo cp /etc/bluetooth/main.conf /etc/bluetooth/main.conf.bak
    sudo sed -i 's/^#\?Experimental *= *false/Experimental = true/' \
        /etc/bluetooth/main.conf
    grep -qE '^Experimental *= *true' /etc/bluetooth/main.conf \
        || echo 'Experimental = true' | sudo tee -a /etc/bluetooth/main.conf >/dev/null
    sudo systemctl restart bluetooth
    echo "   enabled"
else
    echo "   already enabled"
fi

echo "== 4/4 bluetooth adapter up + pairable"
sudo rfkill unblock bluetooth
sudo bluetoothctl power on >/dev/null || true
# A fresh image is Pairable=no, so a BLE MIDI host SEES the pedal advertising
# and then fails to connect (bonding is refused). midi/ble.py sets Pairable at
# startup too; this persists it for bluetoothd itself.
if ! grep -qE '^AlwaysPairable *= *true' /etc/bluetooth/main.conf; then
    sudo sed -i 's/^#\?AlwaysPairable *= *false/AlwaysPairable = true/' \
        /etc/bluetooth/main.conf
    grep -qE '^AlwaysPairable *= *true' /etc/bluetooth/main.conf \
        || echo 'AlwaysPairable = true' | sudo tee -a /etc/bluetooth/main.conf >/dev/null
    sudo systemctl restart bluetooth
fi
sudo bluetoothctl pairable on >/dev/null || true
# A fresh image is also NOT connectable, which is the other half of "the host
# sees the pedal but cannot connect": the advertisement's own connectable flag
# is not enough, the adapter gates incoming connections separately.
sudo btmgmt --index 0 connectable on >/dev/null 2>&1 || true

echo "done — now apply config.txt, ./deploy.sh, then the act-led/splash scripts"
