#!/usr/bin/env bash
# Deploy the app to the Pi and restart the service.
# Usage: ./deploy.sh [host]   (host defaults to "pedal", see ~/.ssh/config)
set -euo pipefail

HOST="${1:-pedal}"
REPO_DIR="$(cd "$(dirname "$0")" && pwd)"

# .lgd-* are root-owned FIFOs lgpio creates at runtime in the working
# directory. --delete cannot unlink them, rsync exits 23, and `set -e` then
# aborts the deploy BEFORE the systemd units are installed — a silent
# half-deploy that is very hard to spot. Leave them alone.
rsync -av --delete --exclude '__pycache__' --exclude '.pytest_cache' \
    --exclude '.lgd-*' \
    "$REPO_DIR/app/" "$HOST:/opt/midi-controller/app/"
rsync -av "$REPO_DIR/scripts/" "$HOST:/opt/midi-controller/scripts/"
rsync -av "$REPO_DIR/systemd/" "$HOST:/tmp/systemd-units/"

ssh "$HOST" '
  set -e
  sudo install -m 644 /tmp/systemd-units/*.service /etc/systemd/system/
  sudo systemctl daemon-reload
  sudo systemctl restart midi-controller
  sleep 2
  systemctl status midi-controller --no-pager -n 5
'
