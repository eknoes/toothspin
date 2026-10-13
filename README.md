# sendspin-bluetooth

Turns a Bluetooth dongle into a speaker that phones can pair with. Whatever
a phone plays shows up in Music Assistant as a live input (a Sendspin
**source**), which you can play on any player or group.

```
Phone ─A2DP─> bluetoothd (host) ─> PipeWire/WirePlumber (core's user session)
      ─pw-record over the PipeWire socket─> sendspin-bluetooth (rootless podman)
      ─Sendspin source@v1 over WebSocket─> Music Assistant (sendspin_source provider)
```

Needs Music Assistant **2.10.6 or newer** (it ships the `sendspin_source`
provider; the service pins `aiosendspin==9.1.1` to match). See
[CLAUDE.md](CLAUDE.md) for background and scope: one dongle; every paired
phone becomes its own Live Input in Music Assistant.

## Setup

On the CoreOS VM ([deploy/coreos](deploy/coreos/)), as `core`, from a copy
of this repo:

1. Layer BlueZ and PipeWire (once):
   ```bash
   sudo rpm-ostree install --apply-live bluez usbutils pipewire wireplumber pipewire-utils
   ```
2. Install our BlueZ config (speaker device class):
   ```bash
   deploy/bluetooth/install.sh
   ```
3. Configure WirePlumber, then build and start the service:
   ```bash
   deploy/service/install.sh
   ```
   `wpctl status` lists a connected phone under Devices; its capture node
   only appears under Sources while the phone is playing.

The web UI is then on `http://<vm>:8080/`. It has no login — keep it on the
home LAN.

### Configuration

Optional, in `~/.config/sendspin-bluetooth.env` (then
`systemctl --user restart sendspin-bluetooth`):

| Variable | Default | |
|---|---|---|
| `SENDSPIN_URL` | discovered via mDNS | e.g. `ws://192.168.178.91:8927/sendspin` |
| `SENDSPIN_NAME` | `{device} (Bluetooth)` | default name of each phone's input in Music Assistant (rename per phone in the web UI) |
| `SENDSPIN_MANUFACTURER` | host name | manufacturer shown for the inputs in Music Assistant |
| `MA_URL` | – | Music Assistant URL, e.g. `http://192.168.178.91:8095`; enables speaker control |
| `MA_TOKEN` | – | long-lived Music Assistant API token (MA profile → tokens); keep the env file `chmod 600` |
| `BT_NAME` | `Music Assistant` | Bluetooth name phones see |
| `SENDSPIN_CODEC` | `pcm` | `pcm`, `flac` or `opus` towards Music Assistant |
| `BT_PAIRING_SECONDS` | `120` | how long "Add phone" keeps pairing open |
| `WEB_PORT` | `8080` | |
| `LOG_LEVEL` | `INFO` | |

## Pairing

Each phone is paired twice, once per layer.

**Phone ↔ Bluetooth:**

1. In the web UI, press **Add phone**. The dongle is discoverable for two
   minutes.
2. On the phone, connect to `BT_NAME`. The first phone that pairs is trusted
   and pairing closes again; outside that window pairing is refused.

**That phone ↔ Music Assistant:** pairing the phone creates its own
Sendspin source, e.g. "Pixel 10 (Bluetooth)", which connects to MA
unpaired. Music Assistant only accepts audio from paired sources.

1. In Music Assistant's settings, open that device and choose **Pair the
   device**, using the dynamic pairing code.
2. On the phone's card in the web UI, press **Allow**. A pairing code
   appears; type it into Music Assistant.

**Playing:** with `MA_URL`/`MA_TOKEN` set, each paired phone's card lists
Music Assistant's speakers as toggles. Turning one on plays the phone there
right away; turning on more groups them on the fly (only speakers that can
play in sync are offered); turning one off takes it out. A speaker playing
another phone is taken over. Without the token: select a player in Music
Assistant, open **Browse**, pick the phone's input and press **Play**. Or set the device's **Automatically play
line-in on** setting: the service reports a signal while the phone plays
non-silent audio, and MA stops a minute after it goes quiet.

Each phone's card in the web UI shows what it plays (title/artist from the
phone), its Music Assistant state, and **Disconnect** / **Remove**.
Removing a phone also forgets its Sendspin identity; remove the matching
device in Music Assistant too.

## Development

```bash
python -m venv .venv && .venv/bin/pip install -e '.[test]'
.venv/bin/pytest
```

`tests/test_source_integration.py` runs the source client against an
in-process aiosendspin server (the library Music Assistant uses): pairing,
line-sense, server-requested start/stop and bit-exact PCM delivery. Phone
capture itself can only be tested with real hardware.
