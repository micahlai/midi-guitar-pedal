#!/bin/sh
# Create a USB MIDI gadget (f_midi) via configfs. Run as root at boot
# (usb-midi-gadget.service). Requires dtoverlay=dwc2,dr_mode=peripheral.
set -e

GADGET=/sys/kernel/config/usb_gadget/midipedal

modprobe libcomposite

if [ -d "$GADGET" ]; then
    echo "gadget already exists"
    exit 0
fi

mkdir -p "$GADGET"
cd "$GADGET"

echo 0x1d6b > idVendor    # Linux Foundation
echo 0x0104 > idProduct   # Multifunction composite gadget
echo 0x0100 > bcdDevice
echo 0x0200 > bcdUSB

mkdir -p strings/0x409
echo "0000001" > strings/0x409/serialnumber
echo "micah" > strings/0x409/manufacturer
echo "Pi MIDI Foot Controller" > strings/0x409/product

mkdir -p configs/c.1/strings/0x409
echo "MIDI" > configs/c.1/strings/0x409/configuration
echo 250 > configs/c.1/MaxPower

mkdir -p functions/midi.usb0
ln -s functions/midi.usb0 configs/c.1/

UDC=$(ls /sys/class/udc | head -n1)
if [ -z "$UDC" ]; then
    echo "no UDC found — is dtoverlay=dwc2,dr_mode=peripheral set?" >&2
    exit 1
fi
echo "$UDC" > UDC
echo "USB MIDI gadget up on $UDC"
