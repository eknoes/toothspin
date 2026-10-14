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

Sendspin's [source role](https://github.com/Sendspin/spec/issues/105) lets
clients capture audio locally and stream it to a server. Music Assistant's
`sendspin_source` provider turns every paired source into a Live Input, and
[aiosendspin](https://github.com/Sendspin/aiosendspin) does the encoding and
streaming. ToothSpin is the capture side: an A2DP sink.

## Host vs. container

Only `bluetoothd` runs on the host: it needs the real HCI socket, which a
rootless container can't open.
Everything else runs in one rootless container: the service plus its own
PipeWire and WirePlumber, on Alpine. The
container talks to `bluetoothd` over the bind-mounted system D-Bus socket.
PipeWire registers the A2DP sink endpoints there and gets each phone's
transport as a file descriptor, so the container never opens a raw Bluetooth
socket.

## Bluetooth side

- A2DP sink only, no HFP/HSP: no calls.
- Each phone shows up as a PipeWire capture node
  (`bluez5.media-source-role = input`), which only exists while the phone is
  playing. The service finds it via `pw-dump`.
- Several phones stream on one adapter at once: `node.always-process = true`
  on `bluez_input.*` makes PipeWire take each phone's stream as soon as it
  starts.
- Only AAC and SBC are offered (`bluez5.codecs`), see the
  [FAQ]({{ '/faq.html#codecs' | relative_url }}).
- On Home Assistant OS, the Supervisor's audio plugin (PulseAudio) loads
  `module-bluetooth-discover` and registers its own A2DP sink, which can win
  the phone's stream. The App (`audio: true`) sees that through the plugin's
  socket and, with the user's consent (an App option), unloads those modules
  with `pactl`, again whenever the plugin restarts, and reconnects the
  phones it held.
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

- ToothSpin doesn't run as root. On the host's system bus, services like
  systemd trust a caller's uid, not its capabilities, so root there could
  ask for anything. Rootless with `--userns keep-id`, it runs as the user,
  and D-Bus sees the user's own uid. With Docker, `--user 1000:1000` runs
  it as the image's `toothspin` user, which owns the image's `/data`, so a
  new volume belongs to it too. Neither needs any capabilities.
- Home Assistant starts Apps as root and gives them a root-owned `/data`;
  an App can't choose its user or the owner of its folders. So there
  ToothSpin reads its options from the Supervisor's API, hands `/data` to
  `toothspin` and switches to it, which needs `CHOWN`, `SETUID` and
  `SETGID` for that moment. Then it has none, and `no-new-privileges`.
- On SELinux hosts, `deploy/selinux/toothspin.cil` defines
  `toothspin.process` from the udica templates container-selinux ships,
  plus the bus socket, `send_msg` to the bus and `bluetoothd` only, and
  mapping PipeWire's memfd buffers.
- As a Home Assistant App it runs under its own AppArmor profile
  (`toothspin/apparmor.txt`): only the capabilities to switch users at
  start, files limited to its programs, its data, `/tmp`, the D-Bus socket
  and Home Assistant's audio socket.
- The web UI has no login. As a Home Assistant App it's served through
  ingress, and the ingress port only answers the Supervisor's proxy
  (172.30.32.2). Outside Home Assistant it relies on the home network.

## As a Home Assistant App

The App (`toothspin/` in the repository) runs the same multi-arch image.
Its options arrive as `/data/options.json` and are mapped onto the same
environment variables the plain container uses. It reaches `bluetoothd`
via `host_dbus` and runs without the host network: it reaches the Music
Assistant App, which runs on the host network, at the host's address on Home
Assistant's internal network (172.30.32.1). An optional port mapping in the
App's Network section serves the web UI to the LAN. Images are built
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

## Standalone mode

Without Music Assistant, ToothSpin can run its own Sendspin server
(`MODE=standalone`), built on aiosendspin's server side, the library Music
Assistant uses too:

- It discovers Sendspin speakers via mDNS and connects to them. Unencrypted
  (pre-1.0, e.g. ESPHome) speakers and speakers allowing unpaired playback
  work; a speaker attached to another server is claimed when it's asked to
  play, before any command (so the start volume isn't lost on the way).
- The phones' Sendspin sources connect to it over localhost exactly as to
  Music Assistant. ToothSpin pairs them itself with a staged pre-shared key.
- It offers the same slice of Music Assistant's player API ToothSpin uses
  (play, stop, group members, volume, group volume, mute), so the web UI and
  the volume sync can't tell the difference.
- It forwards each input to every group playing it. Phone and speakers run
  on different clocks; when the delay drifts more than 20 ms from where it
  started, one sample per 20 ms chunk is dropped or repeated.
- aiosendspin's server needs PyAV (its push stream always resamples), numpy
  and Pillow, about 200 MB, so it ships as a separate `-server` image.

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
version the stable Music Assistant ships: 9.1.1, in every 2.10 release.

- **Older Music Assistant:** Sendspin inputs arrived in 2.10.0, but raw PCM
  input (ToothSpin's default) and token pairing only work since 2.10.2.
  ToothSpin reads Music Assistant's version (from its API, or without a
  token from `/info` or its mDNS announcement) and asks for an update below
  2.10.2.
- **Music Assistant 2.11** (beta as of October 2026) moves to aiosendspin
  10, which follows the Sendspin 1.0 spec. A 10.x *client* can't talk to a
  9.1.1 server, so ToothSpin can't move ahead of the stable Music Assistant.
  The other way round works: a 10.x server accepts 9.1.1 clients as legacy
  clients (logged as non-compliant), and Music Assistant 2.11 allows them by
  default. Tested with 2.10.0, 2.10.5, 2.10.6 and 2.11.0b5: pairing via the
  API and streaming work.
- Once Music Assistant drops legacy clients, or 2.10 is gone, ToothSpin
  moves to aiosendspin 10 and its minimum version follows.
