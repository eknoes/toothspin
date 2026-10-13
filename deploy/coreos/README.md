# CoreOS dev VM provisioning

`config.ign` is a Fedora CoreOS Ignition config: on first boot it adds the
`core` user's SSH key, sets the hostname, and enables `podman.socket` and
`bluetooth.service`. `config.bu` is the equivalent Butane (YAML) source —
kept for readability/future maintenance, but **`config.ign` was
hand-written, not compiled from it**, because the session that authored
this has no root/package-manager access and no nested container runtime to
run `butane` or `coreos-installer` itself. If you have `butane` available,
it's worth running `butane config.bu > config.ign` once to confirm they
still match.

Only `config.ign`'s JSON syntax was validated here (via Python's `json`
module) — it hasn't been test-booted.

## Applying it, without needing `coreos-installer`

You don't need to bake this into a custom ISO. Fedora CoreOS's stock live
ISO can fetch an Ignition config from a URL at boot time:

1. Download the stock Fedora CoreOS **ISO** (stable stream, `metal` or
   `qemu` platform — either works for a Proxmox VM) from
   https://fedoraproject.org/coreos/download — no customization needed.
2. Serve this file over HTTP somewhere reachable from the VM's network,
   e.g. from your workstation or the Proxmox host itself:
   ```
   cd deploy/coreos && python3 -m http.server 8080
   ```
3. Create the VM in Proxmox, attach the ISO, boot it.
4. At the GRUB menu, press `e` to edit the boot entry, and append to the
   `linux` line:
   ```
   ignition.config.url=http://<host-serving-the-file>:8080/config.ign
   ```
   then boot (`Ctrl+X` / `F10` depending on the GRUB build).
5. CoreOS installs itself unattended and reboots with the config applied.
   SSH in as `core` using the key already in `~/.claude/ssh/`.

If you'd rather bake `config.ign` into a customized ISO instead (e.g. for a
fully hands-off install with no HTTP server step), that needs
`coreos-installer iso customize config.ign -o sendspin-bt.iso --dest-ignition
config.ign` run from a host that has `coreos-installer` — not something this
session can produce.

## Post-install packages

The base Fedora CoreOS image doesn't ship `bluez` — Ignition can *enable*
`bluetooth.service`, but the unit doesn't exist until the package is
layered on. This isn't declarative in Ignition (rpm-ostree package layering
needs a reboot to apply), so it's a one-time manual step after first boot:

```bash
sudo rpm-ostree install --apply-live bluez usbutils alsa-lib bluez-libs libsbc fdk-aac-free
```

(`usbutils` is just for `lsusb`-based diagnostics, not required to run
anything. The last four are bluealsa's runtime libraries. `--apply-live`
avoids the reboot for package additions.) After rebooting, confirm with `systemctl is-enabled
bluetooth.service` — if Ignition's first boot ran before the package
existed, the enablement may need to be set manually once:
`sudo systemctl enable --now bluetooth.service`.

`bluez-alsa` (`bluealsad`) isn't packaged for Fedora, so
[`deploy/bluealsa/install.sh`](../bluealsa/install.sh) builds it in a
Fedora container matching the host release and installs it to
`/usr/local/bin`. Rebuild it if a CoreOS update ever bumps one of those
libraries' sonames.
