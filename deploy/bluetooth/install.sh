#!/bin/bash
# Install our BlueZ config on the CoreOS host. Run on the VM as `core`.
set -euo pipefail
cd "$(dirname "$0")"
sudo install -D -m 0644 main.conf /etc/bluetooth/main.conf
sudo systemctl restart bluetooth.service
