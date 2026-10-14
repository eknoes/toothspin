#!/bin/bash
# Build the image from this checkout and (re)start it as a rootless Quadlet
# unit, e.g. for development. Run as the user the service should run as.
# Hosts provisioned from deploy/coreos run the released image instead.
set -euo pipefail
repo="$(cd "$(dirname "$0")/../.." && pwd)"
units=~/.config/containers/systemd

podman build -t localhost/toothspin:latest "$repo"

# The container's SELinux type, which may use the host's D-Bus.
if command -v selinuxenabled >/dev/null && selinuxenabled; then
    sudo semodule -i "$repo/deploy/selinux/toothspin.cil" \
        /usr/share/udica/templates/{base_container,net_container}.cil
fi

# Keep the user's services running without a login.
loginctl enable-linger "$USER"
install -D -m 0644 "$repo/deploy/service/toothspin.container" "$units/toothspin.container"
# Run the image just built rather than the released one.
install -D -m 0644 /dev/stdin "$units/toothspin.container.d/local.conf" <<'UNIT'
[Container]
Image=localhost/toothspin:latest
AutoUpdate=local
UNIT
touch ~/.config/toothspin.env
chmod 600 ~/.config/toothspin.env
# The image runs its own PipeWire; a host PipeWire would register a second
# Bluetooth audio receiver with bluetoothd and compete for the phones.
systemctl --user mask --now pipewire.socket pipewire.service wireplumber.service 2>/dev/null || true
systemctl --user daemon-reload
systemctl --user restart toothspin.service
