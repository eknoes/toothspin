# ToothSpin on Fedora CoreOS

[config.bu](config.bu) sets up a Fedora CoreOS machine (e.g. a Proxmox VM
with the USB Bluetooth dongle passed through) that runs ToothSpin by itself.
On first boot it:

- layers BlueZ and starts `bluetoothd` with ToothSpin's
  [main.conf](../bluetooth/main.conf),
- loads the container's [SELinux policy](../selinux/toothspin.cil),
- starts ToothSpin as a rootless Quadlet unit of the `core` user, pulling
  `ghcr.io/eknoes/toothspin:latest`; `podman-auto-update.timer` keeps it
  on the latest release.

The web UI is then on `http://toothspin:8080/`.

## 1. Your SSH key

Put your SSH public key(s) into `deploy/coreos/authorized_keys`, one per
line, e.g.:

```bash
cp ~/.ssh/id_ed25519.pub deploy/coreos/authorized_keys
```

Git ignores that file, so your key never ends up in the repository. You'll
log in as `core`.

## 2. Build the Ignition config

From the repository root, with [Butane](https://coreos.github.io/butane/getting-started/)
(or its container, as below):

```bash
podman run --rm -v "$PWD:/repo:z" -w /repo quay.io/coreos/butane:release \
  --pretty --strict --files-dir . deploy/coreos/config.bu > toothspin.ign
```

`--files-dir .` lets it embed the BlueZ config, the SELinux policy and the
Quadlet unit from this repository. `*.ign` is ignored by git too.

## 3. Install

Boot the stock Fedora CoreOS live ISO (stable stream,
https://fedoraproject.org/coreos/download) and install with the config,
e.g. served from your machine with `python3 -m http.server`:

```bash
sudo coreos-installer install /dev/sda \
  --ignition-url http://<your-machine>:8000/toothspin.ign --insecure-ignition
sudo reboot
```

(Or embed it into the ISO beforehand: `coreos-installer iso customize
--dest-device /dev/sda --dest-ignition toothspin.ign -o toothspin.iso
fedora-coreos-*.iso`.)

First boot takes a few minutes: layering BlueZ downloads packages, and the
first start pulls the image. Follow it with:

```bash
ssh core@toothspin
journalctl -fu rpm-ostree-install-bluez -u toothspin-selinux
journalctl --user -fu toothspin
```

## Afterwards

- Settings go into `~/.config/toothspin.env` (see the main
  [README](../../README.md#configuration)), then
  `systemctl --user restart toothspin`.
- To run a local build instead of the released image, run
  [deploy/service/install.sh](../service/install.sh) from a checkout on the
  machine.
- Until the image on GHCR is public, the machine can't pull it: log in
  first with `podman login ghcr.io` as `core`, or use `install.sh`.
