#!/bin/bash
# Build the service image and (re)start it as a rootless Quadlet unit.
# Run on the VM as `core` from a checkout of this repo.
set -euo pipefail
repo="$(cd "$(dirname "$0")/../.." && pwd)"

podman build -t localhost/toothspin:latest "$repo"

# The container's SELinux type, which may use the host's D-Bus.
if command -v semodule >/dev/null && selinuxenabled; then
    sudo semodule -i "$repo/deploy/selinux/toothspin.cil" \
        /usr/share/udica/templates/{base_container,net_container}.cil
fi

# Keep core's user services running without an SSH session.
loginctl enable-linger "$USER"
install -D -m 0644 "$repo/deploy/service/toothspin.container" \
    ~/.config/containers/systemd/toothspin.container
touch ~/.config/toothspin.env
chmod 600 ~/.config/toothspin.env
# The image runs its own PipeWire; a host PipeWire would register a second
# Bluetooth audio receiver with bluetoothd and compete for the phones.
systemctl --user mask --now pipewire.socket pipewire.service wireplumber.service 2>/dev/null || true
systemctl --user daemon-reload
systemctl --user restart toothspin.service
