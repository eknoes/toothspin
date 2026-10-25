# ToothSpin Standalone

![Supports aarch64 Architecture][aarch64-shield]
![Supports amd64 Architecture][amd64-shield]

ToothSpin for homes without Music Assistant: it plays phones on Sendspin
speakers only. **With Music Assistant, install ToothSpin (without
Standalone) instead:** it plays on all of Music Assistant's speakers, with
Music Assistant's features.

Your phone pairs with ToothSpin like with any Bluetooth speaker, and
ToothSpin plays it on your Sendspin speakers, one or several in sync. It
runs its own Sendspin server, so it can't run next to Music Assistant's
Sendspin integration: both would fight over the same speakers.

It's young and runs in a couple of homes so far, so expect rough edges. Bug reports
(any volume) are welcome!

## Before you install

- **Sendspin speakers**, e.g. with ESPHome. Speakers that only play for a
  server they're paired with aren't supported yet.
- **A Bluetooth adapter.** ToothSpin can share Home Assistant's, but **a USB
  dongle just for ToothSpin is recommended**: phones stay connected more
  reliably. For a virtual machine, pass the dongle through.
- Not at the same time as the **ToothSpin** App: both need the adapter.

## Installation

1. Install ToothSpin Standalone.
2. With a dongle just for ToothSpin: set **Bluetooth adapter** to it (e.g.
   `hci1`) in the **Configuration** tab, and **ignore or disable it in
   Settings → Devices & services → Bluetooth**. Otherwise keep `hci0`.
3. Start it and open it from the sidebar.

If anything is missing, ToothSpin tells you what to do.

[Installation guide](https://eknoes.github.io/toothspin/install.html#home-assistant) ·
[FAQ](https://eknoes.github.io/toothspin/faq.html)

[aarch64-shield]: https://img.shields.io/badge/aarch64-yes-green.svg
[amd64-shield]: https://img.shields.io/badge/amd64-yes-green.svg
