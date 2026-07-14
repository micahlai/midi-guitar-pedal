#!/usr/bin/env bash
# DNS side of the captive portal: while the pedal is hosting its hotspot,
# resolve EVERY name to the pedal, so the laptop's connectivity probe
# (captive.apple.com, connectivitycheck.gstatic.com, msftconnecttest.com)
# lands on web/portal.py and the OS opens the editor by itself.
#
#   ssh pedal 'bash /opt/midi-controller/scripts/setup-captive-portal.sh'
#
# NetworkManager runs a dnsmasq instance for shared (hotspot) connections and
# reads extra config from /etc/NetworkManager/dnsmasq-shared.d/. That is
# SHARED-MODE ONLY: the pedal's own DNS as a Wi-Fi client is untouched, so
# this cannot break normal networking.
#
# Idempotent; takes effect the next time the hotspot is raised.
# Revert: delete the file below, restart NetworkManager.
set -euo pipefail

CONF=/etc/NetworkManager/dnsmasq-shared.d/captive-portal.conf

sudo mkdir -p "$(dirname "$CONF")"
sudo tee "$CONF" >/dev/null <<'EOF'
# Wildcard: every domain resolves to the hotspot's own address, so the
# client's captive-portal probe reaches the pedal instead of the internet.
# NM substitutes the shared connection's gateway address for a bare
# address=/#/ target, so this needs no hardcoded subnet.
address=/#/10.42.0.1
EOF

echo "wrote $CONF"
sudo systemctl reload NetworkManager 2>/dev/null || sudo systemctl restart NetworkManager
echo "done — raise the hotspot and join it; the editor should open by itself"
