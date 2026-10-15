---
layout: default
title: FAQ
description: Common questions about ToothSpin, Bluetooth adapters and Music Assistant.
lede: Common questions and what to do when something doesn't work.
---

## Setup

### Do I need a second Bluetooth dongle? {#second-dongle}

No, but it's recommended. ToothSpin can share an adapter with Home
Assistant's Bluetooth integration, which only scans for Bluetooth Low Energy
devices (sensors, locks, ...). On a shared adapter, phones may drop out or
the sound may stutter while Home Assistant scans. A cheap USB dongle just for
ToothSpin avoids that. ToothSpin tells you in its web UI when it shares an
adapter.

### How do I keep Home Assistant off ToothSpin's dongle? {#ignore-dongle}

Open **Settings → Devices & services → Bluetooth**. If the dongle is listed
under *Discovered*, choose **Ignore**. If it was added already, open it and
**disable** it (⋮ menu → Disable). Then set ToothSpin's **Bluetooth adapter**
to that dongle, or to `auto`.

### Which adapter is hci0, which is hci1? {#which-adapter}

ToothSpin lists the adapters it found, with their addresses, when the
configured one doesn't exist, and its log names the adapter it uses. Home
Assistant's Bluetooth integration shows each adapter's address too. `auto`
saves you the guessing: it picks one Home Assistant doesn't use.

### Do I need the Music Assistant token? {#token}

ToothSpin works without, but you'll miss most of it: picking speakers per
phone, the phone's volume buttons controlling the speakers, and automatic
pairing with Music Assistant. Create one in Music Assistant (your profile →
**Tokens** → **Create token**) and paste it into ToothSpin's configuration.

### Which Music Assistant versions work? {#ma-versions}

2.10.2 or newer; 2.10.6 or newer is recommended, and ToothSpin is also
tested with the 2.11 beta. With an older one, ToothSpin says so in **Finish
setup** and in its log. If Music Assistant updates and something stops
working, please [open an issue](https://github.com/eknoes/toothspin/issues).

### Where is ToothSpin in Home Assistant? {#sidebar}

In the sidebar. ToothSpin adds itself there on its first start. If you
removed it: **Settings → Apps → ToothSpin → Show in sidebar**.

## Using it

### How do I put ToothSpin on my phone's home screen? {#home-screen}

With the Home Assistant Companion app (Android), a shortcut opens ToothSpin
directly, with Home Assistant's login and also away from home:

1. Find ToothSpin's address: open it from Home Assistant's sidebar in a
   browser and look at the address bar, e.g.
   `http://homeassistant.local:8123/app/8558c230_toothspin`. You need the
   part from `/app/` on.
2. In the Companion app, open **Settings → Companion app → Manage
   shortcuts** and add a shortcut, e.g. labelled *ToothSpin*.
3. Choose the type **Dashboard**. Despite its name, the field *Dashboard
   view or Dashboard* takes any page of Home Assistant: enter the path from
   step 1, e.g. `/app/8558c230_toothspin`.
4. Save it, then long-press the shortcut (or the app icon) to pin it to the
   home screen.

For ToothSpin from `https://github.com/eknoes/toothspin`, the path is
`/app/8558c230_toothspin`.

Without the Companion app: in the App's **Network** section, set a port for
the web interface (e.g. `8080`) and use
"Add to Home screen" in the phone's browser on `http://<Home Assistant's
address>:8080/`. That page has no login of its own, so keep it to your home
network.

### My phone doesn't find ToothSpin {#not-found}

Phones can only pair while the pairing window is open: press **Add phone**
in ToothSpin, then search on the phone within two minutes. Already paired
phones connect like to any Bluetooth speaker.

### The phone shows ToothSpin as a computer {#computer}

The kind of device phones see is set in the host's Bluetooth configuration,
which the Home Assistant App can't change. Audio works either way.

### It's connected, but nothing plays {#no-sound}

As a Home Assistant App: if **Finish setup** asks to *Let ToothSpin receive
the phones' audio*, do that first. Home Assistant's own audio service also
receives Bluetooth audio and otherwise takes the phone's stream.

Music plays from the phone into Music Assistant, and from there on speakers.
Switch on a speaker on the phone's card in ToothSpin (needs the token), or
in Music Assistant select a player, open **Browse**, pick the phone's input
and press **Play**. The phone's input only exists once it's paired with
Music Assistant: with a token that happens by itself, otherwise press
**Allow pairing** on the phone's card and type the code into Music
Assistant.

### Why doesn't Music Assistant show the song title? {#metadata}

Music Assistant only gets the audio from ToothSpin, not what's playing:
Sendspin, the protocol between them, has no way yet for an input to send
the title, artist or cover art. So Music Assistant and your speakers show
just the phone's input. ToothSpin's own web UI shows the title and artist on
the phone's card, as far as the phone reports them over Bluetooth. Support
in Sendspin is being discussed
([Sendspin/backlog#56](https://github.com/Sendspin/backlog/issues/56)).

### Why are the speakers off after a long pause? {#long-pause}

When you pause the phone, ToothSpin keeps its speakers for up to 10 minutes,
so playback continues right where it was. After that, Music Assistant lets
the speakers go, and resuming on the phone doesn't switch them back on:
switch them on again in ToothSpin.

That's a known limitation. Taking the speakers back by itself could cut off
whatever someone else started on them in the meantime. It's on our backlog.

### Can several phones play at once? {#several-phones}

Yes. Each phone is its own input in Music Assistant and can play on its own
speakers.

### How do I stop a speaker from getting too loud? {#max-volume}

Set its **Maximum volume** in Music Assistant's player settings. ToothSpin's
**Maximum start volume** option also limits how loud a speaker starts when a
phone begins playing on it. Speakers that show **Fixed volume** have their volume
set on the speaker or its amplifier.

### Can I take phone calls through it? {#calls}

No. ToothSpin only receives music (A2DP), no calls.

## Trouble

### ToothSpin says something is wrong {#setup-problems}

ToothSpin checks its setup on every start. What's left to do shows up as
**Finish setup** on top of its web UI; open it for step-by-step instructions
with links into Home Assistant. It goes away once everything is done, and
ToothSpin works meanwhile.

<figure class="shot">
  <img src="{{ '/assets/screenshots/setup-collapsed.png' | relative_url }}" width="448"
    alt="Finish setup, collapsed: two things to do">
</figure>

Problems that stop it from starting replace the page instead, and also show
up as a Home Assistant notification. Fix them and ToothSpin starts by itself
within a few seconds.

<figure class="shot">
  <img src="{{ '/assets/screenshots/setup-blocked.png' | relative_url }}" width="448"
    alt="No Bluetooth adapter found, with steps to fix it">
</figure>

### Some speakers won't group, or won't leave a group {#grouping}

ToothSpin says *Music Assistant didn't group … with …*, or Music Assistant
reports an error such as *set_members needs to be implemented*. Often only
one direction fails: the speaker can lead a group, but not join another.

That's usually a stale or reused device in Music Assistant: an old player
entry with the same ID as the speaker, e.g. from software that ran on the
same device before (a Raspberry Pi that was a Squeezelite player before it
became a Sendspin speaker). Music Assistant then mixes the two up and can't
find the speaker's Sendspin output for grouping.

Remove the old entry in Music Assistant (**Settings → Players**), and add
the speaker again if needed. If that doesn't help, please
[open an issue](https://github.com/eknoes/toothspin/issues).

### Something else {#other}

Look at the log (**Settings → Apps → ToothSpin → Log**) and
[open an issue](https://github.com/eknoes/toothspin/issues) with it.
