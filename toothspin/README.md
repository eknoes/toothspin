# ToothSpin

![Supports aarch64 Architecture][aarch64-shield]
![Supports amd64 Architecture][amd64-shield]

Stream any phone over Bluetooth into Music Assistant.

ToothSpin turns a Bluetooth dongle into a speaker your phones can pair
with. Whatever a phone plays shows up in Music Assistant as a live input,
which you can play on any speaker or group, and pick the speakers right from
the app.

## Before you install

You need:

- **Music Assistant 2.10.6 or newer.**
- **A Bluetooth adapter.** ToothSpin can share it with Home Assistant's
  Bluetooth integration, which only uses Bluetooth Low Energy (sensors,
  locks, ...). **We recommend a USB Bluetooth dongle just for ToothSpin**:
  phones stay connected more reliably. If Home Assistant runs in a virtual
  machine, pass the dongle through to it.

## Installation

1. Install ToothSpin and open its **Configuration** tab.
2. **Recommended: in Music Assistant, open your profile → Tokens, create a
   token and paste it as Music Assistant token.** Without it you can't pick
   speakers in ToothSpin, and you have to pair every phone with Music
   Assistant by hand.
3. With a dongle just for ToothSpin: set **Bluetooth adapter** to it (e.g.
   `hci1`, or `auto`), and in **Settings → Devices & services → Bluetooth**
   **ignore or disable that dongle**, so Home Assistant leaves it alone.
   Otherwise keep the default `hci0`.
4. Start ToothSpin and open it from the sidebar.

ToothSpin checks its setup when it starts. If something is missing or could
be better (no adapter, an adapter shared with Home Assistant, no token), it
says what to do, in the app, in the log and, if it can't start, as a Home
Assistant notification.

[aarch64-shield]: https://img.shields.io/badge/aarch64-yes-green.svg
[amd64-shield]: https://img.shields.io/badge/amd64-yes-green.svg
