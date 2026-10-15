# ToothSpin

ToothSpin turns a Bluetooth dongle into a speaker your phones can pair with.
Whatever a phone plays shows up in Music Assistant as a live input (a
Sendspin source), which you can play on any speaker or group.

## Requirements

- **Music Assistant 2.10.6 or newer**, with its Sendspin player provider
  enabled (it is by default). Its "Sendspin Source" plugin turns each phone
  into a live input.
- **A Bluetooth adapter.** ToothSpin takes over the adapter: it sets its
  name, makes it visible while pairing and handles its connections. It can
  share the adapter with Home Assistant's Bluetooth integration, which only
  scans for Bluetooth Low Energy devices, but **a USB dongle just for
  ToothSpin is recommended**: phones stay connected more reliably.

## Installation

1. Install ToothSpin.
2. **Recommended:** create a long-lived token in Music Assistant (your
   profile → **Tokens**) and enter it as **Music Assistant token** in the
   app's **Configuration**.
3. With a dongle just for ToothSpin (for a virtual machine: pass it
   through), set **Bluetooth adapter** to it, e.g. `hci1` or `auto`, and in
   **Settings → Devices & services → Bluetooth** choose **Ignore** for it if
   it's listed under *Discovered*, or **disable** it if it was added.
4. Start the app and open it from the sidebar.

**Bluetooth adapter** is `hci0`, the first adapter, by default. `auto`
picks one Home Assistant's Bluetooth integration doesn't use, and shares one
only if there's no other.

The [installation guide](https://eknoes.github.io/toothspin/install.html#home-assistant) and the
[FAQ](https://eknoes.github.io/toothspin/faq.html) have more detail.

## Setup checks

On every start, and while running, ToothSpin checks:

- **Is there a Bluetooth adapter?** If not, or if the configured one (e.g.
  `hci1`) doesn't exist, it lists the adapters it found and waits.
- **Does Home Assistant use it too?** ToothSpin asks Home Assistant's
  Bluetooth integration and recommends a dongle of its own if it shares
  one. If Home Assistant discovered ToothSpin's dongle and offers to add it,
  ToothSpin recommends ignoring it, and does it for you if you confirm.
- **Home Assistant's audio service:** it also receives Bluetooth audio and
  takes the phones' streams before ToothSpin does (the phone connects, but
  nothing plays). ToothSpin asks to turn that off there; with your OK it sets
  **Take Bluetooth audio from Home Assistant** and keeps it off, also after
  the audio service restarts.
- **Music Assistant token and connection:** missing token, a token Music
  Assistant rejects, or Music Assistant not found.

What's left shows up as **Finish setup** on top of the app, with steps and
links into Home Assistant; it goes away once done. The log says it too. If
ToothSpin can't start (no adapter), it also raises a Home Assistant
notification, checks again every few seconds and starts by itself once the
problem is fixed; the notification then disappears.

## Usage

Each phone is paired twice, once over Bluetooth and once with Music
Assistant.

**Add a phone:** press **Add phone**. The dongle is visible for two minutes;
on the phone, connect to the **Bluetooth name** (default "ToothSpin").
Pairing closes again once a phone has paired.

**Pair with Music Assistant:** each phone becomes its own input, e.g.
"Pixel 10 (Bluetooth)". With a **Music Assistant token** set, ToothSpin
pairs it with Music Assistant by itself. Without, open that device in Music
Assistant's settings and choose **Pair the device**; then press **Allow** on
the phone's card in ToothSpin and type the code it shows into Music
Assistant.

**Connect and play:** connect the phone to ToothSpin like to any Bluetooth
speaker, or press **Connect** on its card. Play something on the phone, then
switch
on one or more speakers on its card. Several speakers form a group on the fly; only speakers that
can play in sync are offered together. Each speaker has its own volume and
mute. To switch rooms, the arrow next to a speaker plays the phone only
there, in one go.

**Volume from the phone:** while a phone plays, its volume buttons control
the speaker, or the whole group if it plays on several. When it starts
playing, the phone takes over the speaker's volume instead of imposing its
own, so nothing suddenly gets loud. To keep a speaker from ever getting too
loud, set its **Maximum volume** in Music Assistant's player settings, or
have speakers start no louder than the **Start volume**.

**Hide speakers:** the eye icon next to a speaker hides it on that phone's
card: it is dimmed and moved to the end of the list. Each phone has its own
hidden speakers.

Without a Music Assistant token, play the input from Music Assistant
instead: select a player, open **Browse**, pick the phone's input and press
**Play**.

## Configuration

| Option | Description |
|---|---|
| Bluetooth name | The name phones see. Default: `ToothSpin`. |
| Input name in Music Assistant | Default name for each phone's input; `{device}` is the phone's name. Each input can be renamed in the app. |
| Bluetooth adapter | `hci0` (default) is the first adapter; set a dedicated dongle, e.g. `hci1`, or `auto` for one Home Assistant doesn't use. |
| Music Assistant token | Recommended. Enables choosing speakers in the app, and pairs phones with Music Assistant automatically. |
| Music Assistant URL | Only needed if Music Assistant doesn't run as an App on this Home Assistant, e.g. `http://192.168.1.10:8095`. |
| Sendspin server URL | Only needed if Music Assistant doesn't run as an App on this Home Assistant, e.g. `ws://192.168.1.10:8927/sendspin`. |
| Start volume | The loudest a speaker starts at (0-100) when a phone starts playing on it, e.g. `20` so a speaker left loud doesn't blast. Quieter speakers keep their volume; `100` (default) always keeps it. |
| Take Bluetooth audio from Home Assistant | Off by default; ToothSpin asks to turn it on. Turns off Bluetooth in Home Assistant's own audio service, which otherwise takes the phones' streams; Home Assistant's audio service then can't use Bluetooth speakers or headsets. To undo, turn it off and restart Home Assistant. |
| Phones may connect by themselves | On (default): paired phones connect by themselves, like to any Bluetooth speaker. Off: connections only start from the app. |
| Log level | `debug`, `info`, `warning` or `error`. |

**Web interface on your network:** in the App's **Network** section, set a
host port for `8080/tcp` (e.g. `8080`). ToothSpin's web interface is then
also at `http://<Home Assistant>:8080/`, **without** Home Assistant's login,
handy for a phone's home screen. Leave it empty to use it only through Home
Assistant.

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

First look at the [FAQ](https://eknoes.github.io/toothspin/faq.html). Questions and bugs:
[GitHub issues](https://github.com/eknoes/toothspin/issues).

## License

GPL-3.0-or-later. Third-party components and their licenses are listed in
[LICENSING.md](https://github.com/eknoes/toothspin/blob/main/LICENSING.md).
