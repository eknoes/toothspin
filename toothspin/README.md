# ToothSpin

![Supports aarch64 Architecture][aarch64-shield]
![Supports amd64 Architecture][amd64-shield]

Stream any phone over Bluetooth into Music Assistant.

ToothSpin turns a Bluetooth adapter into a Bluetooth speaker for Music
Assistant. Your phone pairs with it like with any other speaker, whatever it
plays shows up in Music Assistant as a live input, and you pick the speakers
right in the app. For when your household asks *"Nice. Where's the
Bluetooth?"*.

It's young and runs in one home so far, so expect rough edges. Bug reports
(any volume) are welcome!

## Before you install

- **Music Assistant 2.10.6 or newer.**
- **A Bluetooth adapter.** ToothSpin can share Home Assistant's, but **a
  USB dongle just for ToothSpin is recommended**: phones stay connected more
  reliably. For a virtual machine, pass the dongle through.

## Installation

1. Install ToothSpin and open its **Configuration** tab.
2. **Recommended: paste a Music Assistant token** (in Music Assistant: your
   profile → Tokens → Create token). Without it you can't pick speakers in
   ToothSpin and must pair each phone with Music Assistant by hand.
3. With a dongle just for ToothSpin: set **Bluetooth adapter** to it (e.g.
   `hci1`), and **ignore or disable it in Settings → Devices & services →
   Bluetooth**. Otherwise keep `hci0`.
4. Start ToothSpin and open it from the sidebar.

If anything is missing, ToothSpin tells you what to do.

[Installation guide](https://eknoes.github.io/toothspin/install.html#home-assistant) ·
[FAQ](https://eknoes.github.io/toothspin/faq.html)

![ToothSpin's web UI: a speaker joins the phone's group, its volume goes up, then the phone plays only there](https://eknoes.github.io/toothspin/assets/screenshots/demo.gif)

[aarch64-shield]: https://img.shields.io/badge/aarch64-yes-green.svg
[amd64-shield]: https://img.shields.io/badge/amd64-yes-green.svg
