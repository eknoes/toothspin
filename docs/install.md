---
layout: default
title: Install
description: Install ToothSpin as a Home Assistant App, with Docker or Podman, or on a Fedora CoreOS machine.
lede: Three ways to run it. If you use Home Assistant, take the App.
---

**You need** Music Assistant **2.10.6 or newer** and a Bluetooth adapter. A
USB Bluetooth dongle just for ToothSpin is recommended: phones stay
connected more reliably than on an adapter shared with other Bluetooth
devices.

## Home Assistant App {#home-assistant}

[![Add the repository to Home Assistant](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Feknoes%2Ftoothspin)

1. **Add the repository.** Click the button above, or in Home Assistant open
   **Settings → Apps → App store → ⋮ → Repositories** and add
   `https://github.com/eknoes/toothspin`.
2. **Install ToothSpin** from the App store and open its **Configuration**
   tab.
3. **Paste a Music Assistant token** (recommended). In Music Assistant, click
   your profile (bottom left) → **Tokens** → **Create token**, copy it and
   paste it as **Music Assistant token**. Without it you can't pick speakers
   in ToothSpin, the phone's volume buttons don't control the speakers, and
   you pair every phone with Music Assistant by hand.
4. **Choose the adapter.** The default `hci0` is the first Bluetooth adapter.
   With a dongle just for ToothSpin, set **Bluetooth adapter** to it (e.g.
   `hci1`, or `auto` to pick one Home Assistant doesn't use) and keep Home
   Assistant off it: in **Settings → Devices & services → Bluetooth**,
   choose **Ignore** if it's listed under *Discovered*, or **disable** it
   (⋮ menu → Disable) if it was added.
5. **Start ToothSpin** and open it from the sidebar.
6. **Add a phone:** press **Add phone**, then connect to "ToothSpin" in the
   phone's Bluetooth settings. Play something and switch on a speaker on the
   phone's card.

ToothSpin checks its setup on every start. If something is missing, the app
shows what to do, step by step. If it can't start at all (e.g. no adapter),
you also get a Home Assistant notification, and ToothSpin starts by itself
once it's fixed.

All options are described on the App's **Documentation** tab. Questions:
[FAQ]({{ '/faq.html' | relative_url }}).

## Docker or Podman {#container}

For your own Linux machine. You set up the host side yourself: **BlueZ**
(`bluetoothd`) with the dongle and **no other Bluetooth audio stack** (a
desktop PipeWire or PulseAudio would compete for the phones). The image
brings everything else.

```bash
docker run -d --name toothspin --restart unless-stopped \
  --network host \
  -v /run/dbus/system_bus_socket:/run/dbus/system_bus_socket \
  -v toothspin-data:/data \
  --cap-drop ALL --security-opt no-new-privileges \
  -e MA_TOKEN=<token> \
  ghcr.io/eknoes/toothspin
```

The web UI is on `http://<host>:8080/`. It has no login, so keep it on your
home network. Rootless Podman also needs `--userns keep-id`; SELinux hosts
need a small policy module. All options and details:
[README](https://github.com/eknoes/toothspin#with-docker-or-podman).

## Fedora CoreOS machine {#coreos}

A small VM with the dongle passed through, or a Raspberry Pi 4, set up
completely on first boot from one config file:
[deploy/coreos](https://github.com/eknoes/toothspin/tree/main/deploy/coreos).
