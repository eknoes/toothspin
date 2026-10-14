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

## Web UI

<figure class="shot">
  <img src="{{ '/assets/screenshots/demo.gif' | relative_url }}" width="480" height="663"
    alt="A speaker joins the phone's group, its volume goes up, then the phone plays only there">
  <figcaption>Add a speaker, turn it up, then play only there. Demo data.</figcaption>
</figure>

<figure class="shot">
  <picture>
    <source srcset="{{ '/assets/screenshots/web-ui-dark.png' | relative_url }}" media="(prefers-color-scheme: dark)">
    <img src="{{ '/assets/screenshots/web-ui-light.png' | relative_url }}" width="640" height="949"
      alt="ToothSpin web UI: a phone playing a track on two grouped speakers, and a second phone showing its Music Assistant pairing code">
  </picture>
  <figcaption>One phone playing on a speaker group, one waiting for Music Assistant pairing. Demo data.</figcaption>
</figure>

## What you need

- Music Assistant 2.10.6 or newer.
- A Bluetooth adapter, ideally a USB dongle just for ToothSpin.
- Home Assistant (ToothSpin installs as an App), or a Linux host with
  `bluetoothd` and Docker or Podman.

[Install it]({{ '/install.html' | relative_url }}), or read the
[FAQ]({{ '/faq.html' | relative_url }}). How it fits together: [technical overview]({{ '/overview.html' | relative_url }}).
