# ToothSpin

Your phones pair with ToothSpin like with a Bluetooth speaker. What they
play shows up in Music Assistant as a live input, which you can play on any
speaker or group.

## Requirements

- **Music Assistant 2.10.6 or newer** (its Sendspin provider is on by
  default).
- **A Bluetooth adapter.** ToothSpin can share Home Assistant's, but **a
  USB dongle just for ToothSpin is recommended**: phones stay connected more
  reliably.

## Installation

1. Install ToothSpin.
2. **Recommended:** create a token in Music Assistant (your profile →
   **Tokens**) and enter it as **Music Assistant token** in the app's
   **Configuration**.
3. With a dongle just for ToothSpin (in a virtual machine: pass it
   through): set **Bluetooth adapter** to it, e.g. `hci1` or `auto`. In
   **Settings → Devices & services → Bluetooth**, **ignore** it if it's
   listed under *Discovered*, or **disable** it if it was added.
4. Start the app and open it from the sidebar.

More help: [installation guide](https://eknoes.github.io/toothspin/install.html#home-assistant)
and [FAQ](https://eknoes.github.io/toothspin/faq.html).

## Setup checks

ToothSpin checks its setup when it starts and while it runs: the Bluetooth
adapter, whether Home Assistant uses it too, Home Assistant's own audio
service (which can grab the phones' audio), the Music Assistant token and
connection, and Music Assistant's version.

Anything left to do shows up as **Finish setup** at the top of the app, with
steps and links into Home Assistant. If ToothSpin can't start at all (e.g.
no adapter), you also get a Home Assistant notification, and it starts by
itself once that's fixed.

## Usage

**Add a phone:** press **Add phone**, then connect to "ToothSpin" in the
phone's Bluetooth settings within two minutes.

**Pair with Music Assistant:** each phone becomes its own input, e.g.
"Pixel 10 (Bluetooth)". With a token, ToothSpin pairs it by itself. Without,
open the input in Music Assistant's settings, choose **Pair the device**,
press **Allow pairing** on the phone's card in ToothSpin and enter the code
it shows.

**Play:** connect the phone (by itself, or with **Connect** on its card),
play something and switch on speakers on its card. Several speakers form a
group; only speakers that can play in sync are offered together. The arrow
next to a speaker moves the phone to just that speaker.

**Volume:** while a phone plays, its volume buttons control the speaker or
group. A speaker keeps its volume when a phone starts on it. To limit how
loud a speaker gets, set its **Maximum volume** in Music Assistant, or use
**Maximum start volume**.

**Hide speakers:** the eye icon hides a speaker on that phone's card.

**Without a token:** play the input from Music Assistant: select a player,
open **Browse**, pick the phone's input and press **Play**.

## Configuration

| Option | Description |
|---|---|
| Bluetooth name | The name phones see. Default: `ToothSpin`. |
| Input name in Music Assistant | Default name of each phone's input; `{device}` is the phone's name. |
| Bluetooth adapter | `hci0` (default) is the first adapter. For your own dongle e.g. `hci1`, or `auto` for one Home Assistant doesn't use. |
| Music Assistant token | Recommended. Lets you pick speakers in the app and pairs phones automatically. |
| Music Assistant URL | Only if Music Assistant doesn't run as an App on this Home Assistant, e.g. `http://192.168.1.10:8095`. |
| Sendspin server URL | Same, e.g. `ws://192.168.1.10:8927/sendspin`. |
| Maximum start volume | A speaker set louder than this (0-100) is turned down to it when a phone starts on it, e.g. `20`. `100` (default) never changes the volume. |
| Take Bluetooth audio from Home Assistant | Turns off Bluetooth in Home Assistant's own audio service, which otherwise grabs the phones' audio. ToothSpin asks first. To undo, turn it off and restart Home Assistant. |
| Phones may connect by themselves | On (default): like any Bluetooth speaker. Off: only **Connect** in the app connects a phone. |
| Pairing on other Bluetooth adapters | `accept` (default) or `refuse`: whether devices may pair with this machine's other adapters. ToothSpin's own isn't affected. [Why ToothSpin decides that](https://eknoes.github.io/toothspin/faq.html#other-adapters). |
| Log level | `debug`, `info`, `warning` or `error`. |

**Web interface on your network:** in the app's **Network** section, set a
port for `8080/tcp` (e.g. `8080`). The web interface is then also at
`http://<Home Assistant>:8080/`, **without** Home Assistant's login.

## Notes

- Phones may show ToothSpin as a computer instead of a speaker. Audio works
  either way.
- Removing a phone in ToothSpin also removes it from Music Assistant (with a
  token; otherwise remove it there yourself). App backups include each
  phone's Music Assistant pairing.

## Support

See the [FAQ](https://eknoes.github.io/toothspin/faq.html), or ask on
[GitHub](https://github.com/eknoes/toothspin/issues).

## License

GPL-3.0-or-later. Third-party components:
[LICENSING.md](https://github.com/eknoes/toothspin/blob/main/LICENSING.md).
