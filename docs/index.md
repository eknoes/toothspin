---
layout: default
hero: A Bluetooth speaker input for Music Assistant.
alpha: >-
  This runs in one home on one dongle. Expect rough edges, breaking changes
  and setups that don't work yet. Bug reports are welcome.
---

Pair your phone with a USB Bluetooth dongle like you would with a speaker.
Whatever the phone plays shows up in [Music Assistant](https://music-assistant.io)
as a live input, and you can play it on any player or group from there.

Under the hood it's a Bluetooth A2DP sink that streams to Music Assistant as
a [Sendspin](https://github.com/Sendspin/spec) source. No Music Assistant
fork or custom provider: it uses the `sendspin_source` provider that ships
with Music Assistant 2.10.6.

## What works

- Several phones on one dongle, each its own input in Music Assistant.
- SBC and AAC from the phone; PCM, FLAC or Opus to Music Assistant.
- A small web UI for pairing, connecting, and picking which speakers a phone
  plays on.
- Pairing only while you open a pairing window. No guest mode.

## What you need

- Music Assistant 2.10.6 or newer.
- A Linux host with a Bluetooth dongle and `bluetoothd`, with no other
  Bluetooth audio stack on it.
- Docker or Podman. The image brings its own PipeWire.

How it fits together: [technical overview]({{ '/overview.html' | relative_url }}).
