#!/bin/bash
# Build the service image and (re)start it as a rootless Quadlet unit.
# Run on the VM as `core` from a checkout of this repo.
set -euo pipefail
repo="$(cd "$(dirname "$0")/../.." && pwd)"

podman build -t localhost/sendspin-bluetooth:latest "$repo"

# Keep core's user services running without an SSH session.
loginctl enable-linger "$USER"
install -D -m 0644 "$repo/deploy/service/sendspin-bluetooth.container" \
    ~/.config/containers/systemd/sendspin-bluetooth.container
touch ~/.config/sendspin-bluetooth.env
chmod 600 ~/.config/sendspin-bluetooth.env
# The image runs its own PipeWire; a host PipeWire would register a second
# Bluetooth audio receiver with bluetoothd and compete for the phones.
systemctl --user mask --now pipewire.socket pipewire.service wireplumber.service 2>/dev/null || true
systemctl --user daemon-reload
systemctl --user restart sendspin-bluetooth.service
