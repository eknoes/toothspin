# ToothSpin Standalone

Your phones pair with ToothSpin like with a Bluetooth speaker, and ToothSpin
plays them on your Sendspin speakers: one, or several in sync. It runs its
own Sendspin server, so it needs no Music Assistant.

## Not together with Music Assistant

This App can't run next to Music Assistant with its Sendspin integration:
both are Sendspin servers, both want port 8927 and the same speakers. If you
use Music Assistant, install **ToothSpin** (without Standalone) instead. It
plays the phones through Music Assistant, on all its speakers.

Run only one of the two ToothSpin Apps at a time: both need the Bluetooth
adapter.

## Requirements

- **Sendspin speakers**, e.g. ESPHome ones. Speakers that speak Sendspin
  unencrypted, or allow servers they aren't paired with, work out of the
  box. Speakers that only play for a server they're paired with aren't
  supported yet.
- **A Bluetooth adapter.** ToothSpin can share Home Assistant's, but **a
  USB dongle just for ToothSpin is recommended**: phones stay connected more
  reliably.

## Installation

1. Install ToothSpin Standalone.
2. With a dongle just for ToothSpin (in a virtual machine: pass it
   through): set **Bluetooth adapter** to it, e.g. `hci1` or `auto`. In
   **Settings → Devices & services → Bluetooth**, **ignore** it if it's
   listed under *Discovered*, or **disable** it if it was added.
3. Start the app and open it from the sidebar.

More help: [installation guide](https://eknoes.github.io/toothspin/install.html#home-assistant)
and [FAQ](https://eknoes.github.io/toothspin/faq.html).

## Setup checks

ToothSpin checks its setup when it starts and while it runs: the Bluetooth
adapter, whether Home Assistant uses it too, and Home Assistant's own audio
service (which can grab the phones' audio).

Anything left to do shows up as **Finish setup** at the top of the app, with
steps and links into Home Assistant. If ToothSpin can't start at all (e.g.
no adapter), you also get a Home Assistant notification, and it starts by
itself once that's fixed.

## Usage

**Add a phone:** press **Add phone**, then connect to "ToothSpin" in the
phone's Bluetooth settings within two minutes.

**Play:** connect the phone (by itself, or with **Connect** on its card),
play something and switch on speakers on its card. ToothSpin finds the
Sendspin speakers on your network by itself. Several speakers form a group
and play in sync. The arrow next to a speaker moves the phone to just that
speaker.

**Volume:** while a phone plays, its volume buttons control the speaker or
group. A speaker keeps its volume when a phone starts on it. To keep a
speaker from starting loud, use **Maximum start volume**.

**Hide speakers:** the eye icon hides a speaker on that phone's card.

## Configuration

| Option | Description |
|---|---|
| Bluetooth name | The name phones see. Default: `ToothSpin`. |
| Bluetooth adapter | `hci0` (default) is the first adapter. For your own dongle e.g. `hci1`, or `auto` for one Home Assistant doesn't use. |
| Maximum start volume | A speaker set louder than this is turned down to the maximum start volume when a phone starts on it, e.g. `20`. `100` (default) never changes the volume. |
| Take Bluetooth audio from Home Assistant | Turns off Bluetooth in Home Assistant's own audio service, which otherwise grabs the phones' audio. ToothSpin asks first. To undo, turn it off and restart Home Assistant. |
| Phones may connect by themselves | On (default): like any Bluetooth speaker. Off: only **Connect** in the app connects a phone. |
| Pairing on other Bluetooth adapters | `accept` (default) or `refuse`: whether devices may pair with this machine's other adapters. ToothSpin's own isn't affected. [Why ToothSpin decides that](https://eknoes.github.io/toothspin/faq.html#other-adapters). |
| Speaker buffer (ms) | How far ahead speakers get the audio, for speakers that don't say what they need (older Sendspin versions). Empty: 1000 ms. Less, e.g. `500`, starts playback sooner; too little makes the sound drop out. The log shows the delay when playback starts. |
| Log level | `debug`, `info`, `warning` or `error`. |

## Notes

- This App uses the host's network: its Sendspin server finds the speakers
  via mDNS, and they connect to it on port 8927. Its web interface is only
  reachable through Home Assistant.
- Phones may show ToothSpin as a computer instead of a speaker. Audio works
  either way.
- App backups include each phone's pairing with ToothSpin's server.

## Support

See the [FAQ](https://eknoes.github.io/toothspin/faq.html), or ask on
[GitHub](https://github.com/eknoes/toothspin/issues).

## License

GPL-3.0-or-later. Third-party components:
[LICENSING.md](https://github.com/eknoes/toothspin/blob/main/LICENSING.md).
