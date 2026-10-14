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

### Where is ToothSpin in Home Assistant? {#sidebar}

In the sidebar. ToothSpin adds itself there on its first start. If you
removed it: **Settings → Apps → ToothSpin → Show in sidebar**.

## Using it

### My phone doesn't find ToothSpin {#not-found}

Phones can only pair while the pairing window is open: press **Add phone**
in ToothSpin, then search on the phone within two minutes. Already paired
phones connect like to any Bluetooth speaker.

### The phone shows ToothSpin as a computer {#computer}

The kind of device phones see is set in the host's Bluetooth configuration,
which the Home Assistant App can't change. Audio works either way.

### It's connected, but nothing plays {#no-sound}

Music plays from the phone into Music Assistant, and from there on speakers.
Switch on a speaker on the phone's card in ToothSpin (needs the token), or
in Music Assistant select a player, open **Browse**, pick the phone's input
and press **Play**. The phone's input only exists once it's paired with
Music Assistant: with a token that happens by itself, otherwise press
**Allow pairing** on the phone's card and type the code into Music
Assistant.

### Can several phones play at once? {#several-phones}

Yes. Each phone is its own input in Music Assistant and can play on its own
speakers.

### How do I stop a speaker from getting too loud? {#max-volume}

Set its **Maximum volume** in Music Assistant's player settings. ToothSpin's
**Start volume** option also limits how loud a speaker starts when a phone
begins playing on it. Speakers that show **Fixed volume** have their volume
set on the speaker or its amplifier.

### Can I take phone calls through it? {#calls}

No. ToothSpin only receives music (A2DP), no calls.

## Trouble

### ToothSpin says something is wrong {#setup-problems}

ToothSpin checks its setup on every start and shows what to do in its web
UI, step by step. Problems that stop it from starting also show up as a Home
Assistant notification. Fix them and ToothSpin starts by itself within a few
seconds.

### Something else {#other}

Look at the log (**Settings → Apps → ToothSpin → Log**) and
[open an issue](https://github.com/eknoes/toothspin/issues) with it.
