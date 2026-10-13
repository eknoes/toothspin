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
- Several phones can stream on one adapter at once. PipeWire only acquires a
  phone's stream once its node runs, so `node.always-process = true` is set
  on `bluez_input.*`.
- The service runs its own BlueZ pairing agent (Just Works). Pairing is
  refused outside the window you open in the web UI, and connections are
  started from the receiver, not the phone.

## Music Assistant side

- Every phone gets its own Sendspin client identity and appears as its own
  Live Input.
- Music Assistant only activates `source@v1` on a paired connection. Pairing
  uses Sendspin's Noise-based dynamic pairing code, shown in the web UI.
  Removing a phone deletes its identity too.
- The service reports a line-sense signal while the phone plays non-silent
  audio, so Music Assistant's auto-play on line-in works.
- With a Music Assistant API token, the web UI can start the phone on
  speakers and group them directly.
- Stream codec towards Music Assistant: PCM (default), FLAC or Opus.

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
