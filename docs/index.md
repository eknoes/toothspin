---
layout: default
hero: A Bluetooth speaker input for Music Assistant.
install_button: true
alpha: >-
  This runs in one home on one dongle so far. Expect rough edges, breaking
  changes and setups that don't work yet. Bug reports (any volume) are welcome!
---

ToothSpin turns a USB Bluetooth dongle into a Bluetooth speaker for
[Music Assistant](https://music-assistant.io). You pair your phone with it like
with any other speaker, and whatever it plays shows up in Music Assistant as
a live input. From there it plays on one speaker, a group, or the whole house.

I built it because my household's review of our multi-room setup was
*"Nice. Where's the Bluetooth?"*

Under the hood it's a Bluetooth A2DP sink that streams to Music Assistant as
a [Sendspin](https://github.com/Sendspin/spec) source. You don't need a Music
Assistant fork or a custom provider: it uses the `sendspin_source` provider
that ships with Music Assistant 2.10.6.

## What works

- Several phones on one dongle, each with its own input in Music Assistant.
- SBC and AAC from the phone; PCM, FLAC or Opus to Music Assistant.
- A small web UI for pairing, connecting, and picking which speakers a phone
  plays on.
- Pairing only while you open the pairing window. There is no guest mode.

## Not working yet

- Song title and cover in Music Assistant: Sendspin can't send them for an
  input yet. ToothSpin's web UI shows them though.
- After a pause of more than 10 minutes, you have to switch the speakers on
  again.

## Web UI

<figure class="shot">
  <img src="{{ '/assets/screenshots/demo.gif' | relative_url }}" width="480" height="663"
    alt="A speaker joins the phone's group, its volume goes up, then the phone plays only there">
  <figcaption>Add a speaker, turn it up, then play only there.</figcaption>
</figure>

<figure class="shot">
  <picture>
    <source srcset="{{ '/assets/screenshots/web-ui-dark.png' | relative_url }}" media="(prefers-color-scheme: dark)">
    <img src="{{ '/assets/screenshots/web-ui-light.png' | relative_url }}" width="640" height="949"
      alt="ToothSpin web UI: a phone playing a track on two grouped speakers, and a second phone showing its Music Assistant pairing code">
  </picture>
  <figcaption>One phone playing on a speaker group, one waiting for Music Assistant pairing.</figcaption>
</figure>

## What you need

- Music Assistant 2.10.6 or newer.
- A Bluetooth adapter, ideally a USB dongle just for ToothSpin.
- Home Assistant (ToothSpin installs as an App), or a Linux host with
  `bluetoothd` and Docker or Podman.
- One or several speakers connected to Music Assistant. I use [Louder Esparagus](https://github.com/sonocotta/esparagus-media-center#louder-esparagus) and some Raspberry Pis with [PiCorePlayer](https://www.picoreplayer.org/).

[Install it]({{ '/install.html' | relative_url }}), or read the
[FAQ]({{ '/faq.html' | relative_url }}). How it fits together: [technical overview]({{ '/overview.html' | relative_url }}).
