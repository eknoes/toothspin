#!/bin/bash
# Install our BlueZ config on the host. With --pin, also turn Secure Simple
# Pairing off so phones ask for BT_PIN (see pin-pairing.conf).
set -euo pipefail
cd "$(dirname "$0")"
sudo install -D -m 0644 main.conf /etc/bluetooth/main.conf
dropin=/etc/systemd/system/bluetooth.service.d/toothspin-pin.conf
if [[ "${1:-}" == "--pin" ]]; then
    sudo install -D -m 0644 pin-pairing.conf "$dropin"
else
    sudo rm -f "$dropin"
fi
sudo systemctl daemon-reload
sudo systemctl restart bluetooth.service
if [[ "${1:-}" != "--pin" ]]; then
    # bluetoothd doesn't switch Secure Simple Pairing back on by itself.
    sudo btmgmt --index 0 ssp on >/dev/null
fi
