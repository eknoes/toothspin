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
install -D -m 0644 "$repo/deploy/pipewire/50-sendspin-bluetooth.conf" \
    ~/.config/wireplumber/wireplumber.conf.d/50-sendspin-bluetooth.conf
touch ~/.config/sendspin-bluetooth.env
systemctl --user daemon-reload
systemctl --user enable --now pipewire.socket wireplumber.service
systemctl --user restart wireplumber.service
systemctl --user restart sendspin-bluetooth.service
