---
layout: default
hero: Stream any phone over Bluetooth to your multi-room speakers, with or without Music Assistant.
install_button: true
alpha: >-
  This runs in a couple of homes so far. Expect rough edges, breaking
  changes and setups that don't work yet. Bug reports (any volume) are welcome!
---

ToothSpin turns a USB Bluetooth dongle into a Bluetooth speaker for
[Music Assistant](https://music-assistant.io). You pair your phone with it like
with any other speaker, and whatever it plays shows up in Music Assistant as
a live input. From there it plays on one speaker, a group, or the whole house.

<p class="diagram">
  <img src="{{ '/assets/how-it-works.svg' | relative_url }}" width="900" height="330"
    alt="Your phone sends audio via Bluetooth to ToothSpin, which forwards it via Sendspin to your speakers, through Music Assistant or directly with ToothSpin Standalone">
</p>

I built it because my household's review of our multi-room setup was
*"Nice. Where's the Bluetooth?"*

Only phones over Bluetooth, and only Sendspin speakers? Then **ToothSpin
Standalone** plays them without Music Assistant:
[which one fits]({{ '/install.html#standalone' | relative_url }}).

Under the hood it's a Bluetooth A2DP sink that streams to Music Assistant as
a [Sendspin](https://github.com/Sendspin/spec) source (or, Standalone, straight
to the speakers). You don't need a Music
Assistant fork or a custom provider: it uses the `sendspin_source` provider
that ships with Music Assistant 2.10.7.

## What works

- Several phones on one dongle, each with its own input in Music Assistant.
- SBC and AAC from the phone; PCM, FLAC or Opus to Music Assistant.
- A small web UI for pairing, connecting, and picking which speakers a phone
  plays on, with title, artist and cover of what it plays.
- ToothSpin Standalone: the same without Music Assistant, on Sendspin
  speakers, with fixed speaker groups and track info on speakers with a
  display.
- Pairing only while you open the pairing window. There is no guest mode.

## Not working yet

- Song title and cover in Music Assistant: Sendspin can't send them for an
  input yet. ToothSpin's web UI shows them though, and ToothSpin Standalone
  sends them to the speakers.
- With Music Assistant: after a pause of more than 10 minutes, you have to
  switch the speakers on again.

## Web UI

<figure class="shot">
  <img src="{{ '/assets/screenshots/demo.gif' | relative_url }}" width="480" height="683"
    alt="A speaker joins the phone's group, its volume goes up, then the phone plays only there">
  <figcaption>Add a speaker, turn it up, then play only there.</figcaption>
</figure>

<figure class="shot">
  <picture>
    <source srcset="{{ '/assets/screenshots/web-ui-dark.png' | relative_url }}" media="(prefers-color-scheme: dark)">
    <img src="{{ '/assets/screenshots/web-ui-light.png' | relative_url }}" width="640" height="1015"
      alt="ToothSpin web UI: a phone playing a track on two grouped speakers, and a second phone showing its Music Assistant pairing code">
  </picture>
  <figcaption>One phone playing on a speaker group, one waiting for Music Assistant pairing.</figcaption>
</figure>

## What you need

- Music Assistant 2.10.7 or newer (not for ToothSpin Standalone).
- A Bluetooth adapter, ideally a USB dongle just for ToothSpin.
- Home Assistant (ToothSpin installs as an App), or a Linux host with
  `bluetoothd` and Docker or Podman.
- Speakers: any that Music Assistant plays on, or Sendspin speakers for
  ToothSpin Standalone.

## Tested hardware

Any Bluetooth adapter Linux supports should work, as long as it does
Bluetooth Classic with A2DP, which phones use for music. ToothSpin is an
A2DP sink with AAC and SBC only: no calls (HFP/HSP) and no LE Audio (LC3,
Auracast). Most USB dongles work with Linux's standard driver. The host
needs BlueZ 5.51 or newer, and 5.79 or newer for covers; current Home
Assistant OS has that.

What ToothSpin runs on every day at my home:

- **Bluetooth:** a BARROT Bluetooth 6.0 USB dongle (`33fa:0012`), passed
  through to the Home Assistant VM; Android phones.
- **Speakers**, with Music Assistant and in standalone mode:
  - [Louder Esparagus](https://github.com/sonocotta/esparagus-media-center#louder-esparagus)
    and [Louder-ESP32 Mini](https://github.com/sonocotta/esp32-audio-dock#louder-esp32-mini)
    with ESPHome
  - [HiFi-ESP32](https://github.com/sonocotta/esp32-audio-dock#hifi-esp32-and-hifi-esp32-plus)
    with ESPHome, into a stereo amplifier
  - Raspberry Pis with [piCorePlayer](https://www.picoreplayer.org/) and
    `sendspin-cpp-cli`

[Install it]({{ '/install.html' | relative_url }}), or read the
[FAQ]({{ '/faq.html' | relative_url }}). How it fits together: [technical overview]({{ '/overview.html' | relative_url }}).
