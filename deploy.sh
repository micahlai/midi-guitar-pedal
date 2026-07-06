#!/usr/bin/env bash
# Deploy the app to the Pi and restart the service.
# Usage: ./deploy.sh [host]   (host defaults to "pedal", see ~/.ssh/config)
set -euo pipefail

HOST="${1:-pedal}"
REPO_DIR="$(cd "$(dirname "$0")" && pwd)"

rsync -av --delete --exclude '__pycache__' "$REPO_DIR/app/" "$HOST:/opt/midi-controller/app/"
rsync -av "$REPO_DIR/systemd/midi-controller.service" "$HOST:/tmp/midi-controller.service"

ssh "$HOST" '
  set -e
  sudo install -m 644 /tmp/midi-controller.service /etc/systemd/system/midi-controller.service
  sudo systemctl daemon-reload
  sudo systemctl restart midi-controller
  sleep 2
  systemctl status midi-controller --no-pager -n 5
'
