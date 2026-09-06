#!/usr/bin/env bash
# Installs the udev rule (needs sudo) and a systemd --user service for g13d,
# so the daemon starts automatically at login and reconnects the G13
# without root. Run from a checkout of this repo with the venv already
# set up (pip install -e .).
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_BIN="$REPO_DIR/.venv/bin"

if [ ! -x "$VENV_BIN/g13d" ]; then
    echo "error: $VENV_BIN/g13d not found -- run 'pip install -e .' in the venv first" >&2
    exit 1
fi

echo "Installing udev rule (needs sudo)..."
sudo cp "$REPO_DIR/udev/99-g13.rules" /etc/udev/rules.d/99-g13.rules
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=usb --attr-match=idVendor=046d --attr-match=idProduct=c21c

echo "Installing systemd --user service..."
mkdir -p ~/.config/systemd/user
sed "s#{{VENV_BIN}}#$VENV_BIN#g" "$REPO_DIR/systemd/g13d.service.in" > ~/.config/systemd/user/g13d.service
systemctl --user daemon-reload
systemctl --user enable --now g13d.service

echo "Done. Check status with: systemctl --user status g13d.service"
