# ToothSpin

ToothSpin turns a Bluetooth dongle into a speaker your phones can pair with.
Whatever a phone plays shows up in Music Assistant as a live input (a
Sendspin source), which you can play on any speaker or group.

## Requirements

- **Music Assistant 2.10.6 or newer**, with its Sendspin player provider
  enabled (it is by default). Its "Sendspin Source" plugin turns each phone
  into a live input.
- **A dedicated USB Bluetooth dongle.** ToothSpin takes over the adapter:
  it sets its name, makes it visible while pairing and handles its
  connections. Don't use the adapter Home Assistant uses for its own
  Bluetooth devices.

## Installation

1. Add this repository to Home Assistant: **Settings → Apps → App store →
   ⋮ → Repositories**, then add `https://github.com/eknoes/toothspin`.
2. Install **ToothSpin**.
3. In **Settings → Devices & services → Bluetooth**, open the dongle you
   want ToothSpin to use and **disable** it there, so Home Assistant doesn't
   use it for its own Bluetooth devices at the same time.
4. In the app's **Configuration**, set **Bluetooth adapter** to that dongle
   (e.g. `hci1`; the Bluetooth integration shows which is which).
5. Optional, for choosing speakers in the app: create a long-lived token in
   Music Assistant (your profile → **Tokens**) and enter it as **Music
   Assistant token**.
6. Start the app and open it with **Open web UI** (or from the sidebar).

## Usage

Each phone is paired twice, once over Bluetooth and once with Music
Assistant.

**Add a phone:** press **Add phone**. The dongle is visible for two minutes;
on the phone, connect to the **Bluetooth name** (default "Music Assistant").
Pairing closes again once a phone has paired.

**Pair with Music Assistant:** each phone becomes its own input, e.g.
"Pixel 10 (Bluetooth)". With a **Music Assistant token** set, ToothSpin
pairs it with Music Assistant by itself. Without, open that device in Music
Assistant's settings and choose **Pair the device**; then press **Allow** on
the phone's card in ToothSpin and type the code it shows into Music
Assistant.

**Connect and play:** connections start from ToothSpin: press **Connect**
on the phone's card. A phone trying to connect by itself is refused, unless
you allow it in the configuration. Play something on the phone, then switch
on one or more speakers on its card. Several speakers form a group on the fly; only speakers that
can play in sync are offered together. Each speaker has its own volume and
mute. To switch rooms, the arrow next to a speaker plays the phone only
there, in one go.

**Volume from the phone:** while a phone plays, its volume buttons control
the speaker, or the whole group if it plays on several. When it starts
playing, the phone takes over the speaker's volume instead of imposing its
own, and a speaker left loud starts at the **Start volume** (20 by default),
so nothing suddenly gets loud.

**Hide speakers:** the eye icon next to a speaker hides it on that phone's
card: it is dimmed and moved to the end of the list. Each phone has its own
hidden speakers.

Without a Music Assistant token, play the input from Music Assistant
instead: select a player, open **Browse**, pick the phone's input and press
**Play**.

## Configuration

| Option | Description |
|---|---|
| Bluetooth name | The name phones see. Default: `Music Assistant`. |
| Input name in Music Assistant | Default name for each phone's input; `{device}` is the phone's name. Each input can be renamed in the app. |
| Bluetooth adapter | The dongle phones connect to, e.g. `hci0` or `hci1`. |
| Music Assistant token | Enables choosing speakers in the app, and pairs phones with Music Assistant automatically. |
| Music Assistant URL | Only needed if Music Assistant isn't found automatically, e.g. `http://homeassistant.local:8095`. |
| Sendspin server URL | Only needed if Music Assistant's Sendspin server isn't found automatically, e.g. `ws://homeassistant.local:8927/sendspin`. |
| Start volume | The loudest a speaker starts at (0-100) when a phone starts playing on it. Quieter speakers keep their volume; `100` always keeps it. Default: `20`. |
| Phones may connect by themselves | Off (default): connections only start from the app. On: paired phones may also connect by themselves. |
| LAN port | Also serves the web interface on this port to your whole network, **without** Home Assistant's login. Handy for adding it to a phone's home screen; leave it empty otherwise. |
| Log level | `debug`, `info`, `warning` or `error`. |

## Notes

- Phones may list the dongle as a computer rather than a speaker: the
  device class is set in the host's BlueZ configuration, which the app
  doesn't change. Audio works either way.
- ToothSpin's audio stack offers to receive Bluetooth audio on every
  adapter of the host, not only the configured one. Phones can only pair
  through ToothSpin's pairing window on its own adapter, so in practice only
  that one is used.
- Music Assistant identifies each phone's input by a key stored in the
  app's data. Removing a phone in ToothSpin also removes that key, and with
  a Music Assistant token the device in Music Assistant too (without, remove
  it there yourself). App backups include the keys.

## Support

Questions and bugs: [GitHub issues](https://github.com/eknoes/toothspin/issues).

## License

GPL-3.0-or-later. Third-party components and their licenses are listed in
[LICENSING.md](https://github.com/eknoes/toothspin/blob/main/LICENSING.md).
