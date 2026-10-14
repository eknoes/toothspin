# Changelog

All notable changes to this app are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.1.0]

### Added

- First release as a Home Assistant App: Bluetooth A2DP receiver that
  streams each paired phone into Music Assistant as its own Sendspin input.
- Web interface through Home Assistant's ingress: pair phones, pair them
  with Music Assistant, connect them, and pick speakers per phone with
  volume and mute.
- Hide speakers per phone: hidden speakers are dimmed and listed last.
- The phone's volume buttons control the speaker or group it plays on;
  on connecting, the phone takes over the speaker's current volume.
