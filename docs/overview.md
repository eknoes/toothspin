---
layout: default
title: Technical overview
description: How ToothSpin gets audio from a phone over Bluetooth into Music Assistant.
lede: How audio gets from a phone into Music Assistant.
alpha: Details below may change between releases.
---

## Pipeline

```text
Phone (A2DP source)
  ─Bluetooth─> hci0 ─> bluetoothd (host)
  ─D-Bus─>     PipeWire bluez5, A2DP sink (container)
  ─pw-record, 48 kHz s16─> capture ─> aiosendspin SourceCapture
  ─Sendspin source@v1 over WebSocket─> Music Assistant sendspin_source
```

Music Assistant had no way to receive audio over Bluetooth, but most of the
pieces already existed upstream. Sendspin added a
[source role](https://github.com/Sendspin/spec/issues/105) for clients that
capture audio locally, Music Assistant's `sendspin_source` provider turns
every paired source into a Live Input, and
[aiosendspin](https://github.com/Sendspin/aiosendspin) does the encoding and
streaming. ToothSpin adds the missing capture backend: an A2DP sink instead
of a sound card.

## Host vs. container

Only `bluetoothd` runs on the host, because it needs the real HCI socket.
Everything else runs in one rootless container: the service plus its own
PipeWire and WirePlumber, on Alpine (Debian's PipeWire lacks AAC). The
container talks to `bluetoothd` over the bind-mounted system D-Bus socket.
PipeWire registers the A2DP sink endpoints there and gets each phone's
transport as a file descriptor, so the container never opens a raw Bluetooth
socket.

That split matters. Bluetooth/HCI sockets resolve against the kernel's
initial user namespace, so BlueZ itself can't run in a rootless container,
no matter which capabilities or flags you give it. A full VM with USB
passthrough works fine, because it has its own kernel.

## Bluetooth side

- A2DP sink only, no HFP/HSP, to avoid profile-switching trouble.
- Each phone shows up as a PipeWire capture node
  (`bluez5.media-source-role = input`), which only exists while the phone is
  playing. The service finds it via `pw-dump`.
- Several phones can stream on one adapter at once. The early assumption
  that BlueZ only allows one was wrong (`bluez/bluez#1037` is about a PC
  *sending* to two speakers). What actually blocked a second stream was
  PipeWire, which only acquires a phone's stream once its node runs, so
  `node.always-process = true` is set on `bluez_input.*`.
- Capture stays at full scale (`bluez5.enable-hw-volume = false`); the
  phone's volume buttons control the speakers instead, see below.
- The service runs its own BlueZ pairing agent (Just Works). Pairing is
  refused outside the window you open in the web UI (or without the PIN,
  with `BT_PIN`). Paired phones connect by themselves; with
  `ALLOW_PHONE_CONNECT=false` only the web UI's **Connect** starts a
  connection, and the agent refuses the phone's own.

## Music Assistant side

- Every phone gets its own Sendspin client identity and appears as its own
  Live Input.
- Music Assistant only activates `source@v1` on a paired connection. With
  an API token ToothSpin pairs automatically (see below); without, pairing
  uses Sendspin's Noise-based dynamic pairing code, shown in the web UI.
  Removing a phone deletes its identity too.
- The service reports a line-sense signal while the phone plays non-silent
  audio, so Music Assistant's auto-play on line-in works.
- With a Music Assistant API token, the web UI can start the phone on
  speakers and group them directly.
- Stream codec towards Music Assistant: PCM (default), FLAC or Opus.

## Volume

While a phone streams, its volume and the volume of the speaker (or group)
it plays on are kept in sync both ways. ToothSpin polls the phone's AVRCP
absolute volume (`MediaTransport1.Volume`, 0–127) and Music Assistant's
player or group volume. When a phone starts streaming, the speaker wins:
its volume is written to the phone (BlueZ forwards that to the phone while
the transport is active), so a phone left at full volume doesn't blast the
room. After that, whichever side changes is copied to the other, ignoring
the echo of its own last write for a few seconds.

## Running confined

- The container needs no Linux capabilities: it runs with `--cap-drop ALL`
  and `no-new-privileges`, and rootless with `--userns keep-id`, so D-Bus
  sees the user's own uid.
- On SELinux hosts, the standard `container_t` may not connect to the
  host's system bus. Rather than disabling SELinux for the container,
  `deploy/selinux/toothspin.cil` defines `toothspin.process` from the udica
  templates container-selinux ships, plus the bus socket, `send_msg` to the
  bus and `bluetoothd` only, and mapping PipeWire's memfd buffers.
- The web UI has no login. As a Home Assistant App it's served through
  ingress, and the ingress port only answers the Supervisor's proxy
  (172.30.32.2). Outside Home Assistant it relies on the home network.

## As a Home Assistant App

The App (`toothspin/` in the repository) runs the same multi-arch image.
Its options arrive as `/data/options.json` and are mapped onto the same
environment variables the plain container uses. It reaches `bluetoothd`
via `host_dbus`, finds Music Assistant via mDNS on the host network and asks
the Supervisor for its ingress port (`ingress_port: 0`). Images are built
and scanned in CI; each release ships SPDX and CycloneDX SBOMs.

The App asks Home Assistant's Bluetooth integration (WebSocket
`config_entries/get` and `config_entries/flow/progress` via
`homeassistant_api`) which adapters it uses, reading each adapter's address
from its config entry title. The integration only scans for Bluetooth Low
Energy, so sharing an adapter works, but ToothSpin recommends a dongle of its
own when it shares one; `BT_ADAPTER=auto` prefers a free one. Setup problems
are shown in the web UI and the log; blocking ones also as a persistent
notification, re-checked until solved. On its first start the App puts
itself in the sidebar (`ingress_panel`, once, so turning it off sticks).

## Pairing with Music Assistant automatically

Pairing a phone over Bluetooth already is the user's consent. With a token
for Music Assistant's API, ToothSpin answers MA's "Pair the device" setup
flow itself (`config/players/setup`, `config/flows/submit`): the phone's
source accepts a fresh pre-shared key, and MA receives it as a pairing token.
MA offers token pairing only to devices without a PIN method, so with a
token the sources offer just that. Removing a phone says goodbye for good
(MA keeps devices that only restart) and then removes it from MA.

## Pairing with a PIN

`BT_PIN` lets phones pair at any time with a fixed PIN instead of only in
the pairing window. That's legacy PIN pairing: phones only use it when the
adapter has Secure Simple Pairing off, which only the host can switch
(`btmgmt ssp off` after bluetoothd starts). Phones paired before keep
working. Legacy pairing is weaker than SSP and has no retry limit, so the
PIN must have at least 6 digits.

## Versions

`source@v1` is young and still changing. ToothSpin pins `aiosendspin` to the
version Music Assistant ships (9.1.1 for 2.10.6), because newer releases
renamed protocol messages and break against older servers. The two get
bumped together.

## Things that were tried and dropped

- **bluez-alsa**: v5.0.0 lost its D-Bus connection on every PCM open on the
  test host and took `bluetoothd` down with it.
- **BlueZ in a rootless container**: blocked by the user-namespace limitation
  above.
