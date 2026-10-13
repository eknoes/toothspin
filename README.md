# sendspin-bluetooth

Turns a Bluetooth dongle into a speaker that phones can pair with. Whatever
a phone plays shows up in Music Assistant as a live input (a Sendspin
**source**), which you can play on any player or group.

```
Phone ─A2DP─> bluetoothd + bluealsa (host) ─PCM fd over D-Bus─> sendspin-bluetooth (rootless podman)
      ─Sendspin source@v1 over WebSocket─> Music Assistant (sendspin_source provider)
```

Needs Music Assistant **2.10.6 or newer** (it ships the `sendspin_source`
provider; the service pins `aiosendspin==9.1.1` to match). See
[CLAUDE.md](CLAUDE.md) for background and scope: one dongle, one phone
connected at a time.

## Setup

On the CoreOS VM ([deploy/coreos](deploy/coreos/)), as `core`, from a copy
of this repo:

1. Layer the Bluetooth packages and bluealsa's runtime libraries (once):
   ```bash
   sudo rpm-ostree install --apply-live bluez usbutils alsa-lib bluez-libs libsbc fdk-aac-free
   ```
2. Build and install bluealsa, our BlueZ config and the D-Bus policy:
   ```bash
   deploy/bluealsa/install.sh
   ```
   `bluealsactl status` should list `A2DP-sink : SBC AAC`.
3. Build and start the service:
   ```bash
   deploy/service/install.sh
   ```

The web UI is then on `http://<vm>:8080/`. It has no login — keep it on the
home LAN.

### Configuration

Optional, in `~/.config/sendspin-bluetooth.env` (then
`systemctl --user restart sendspin-bluetooth`):

| Variable | Default | |
|---|---|---|
| `SENDSPIN_URL` | discovered via mDNS | e.g. `ws://192.168.178.91:8927/sendspin` |
| `SENDSPIN_NAME` | `Bluetooth` | name of the input in Music Assistant |
| `BT_NAME` | `Music Assistant` | Bluetooth name phones see |
| `SENDSPIN_CODEC` | `pcm` | `pcm`, `flac` or `opus` towards Music Assistant |
| `BT_PAIRING_SECONDS` | `120` | how long "Add phone" keeps pairing open |
| `WEB_PORT` | `8080` | |
| `LOG_LEVEL` | `INFO` | |

## Pairing

Two separate one-time pairings.

**Music Assistant ↔ this service** (once per MA server):

1. The service connects to MA on its own and shows up unpaired. Music
   Assistant only accepts audio from paired sources.
2. In Music Assistant's settings, open the device (named `SENDSPIN_NAME`)
   and choose **Pair the device**, using the dynamic pairing code.
3. In the web UI, press **Allow** (or **Allow pairing** beforehand). A
   pairing code appears; type it into Music Assistant.

**Phone ↔ Bluetooth** (once per phone):

1. In the web UI, press **Add phone**. The dongle is discoverable for two
   minutes.
2. On the phone, connect to `BT_NAME`. The first phone that pairs is trusted
   and pairing closes again; outside that window pairing is refused.
3. Play something. The input appears under Music Assistant's live inputs.

To play automatically, set a target under the device's **Automatically play
line-in on** setting in Music Assistant: the service reports a signal while
the phone plays non-silent audio, and MA stops a minute after it goes quiet.

Phones are listed in the web UI with **Disconnect** and **Remove**.

## Development

```bash
python -m venv .venv && .venv/bin/pip install -e '.[test]'
.venv/bin/pytest
```

`tests/test_source_integration.py` runs the source client against an
in-process aiosendspin server (the library Music Assistant uses): pairing,
line-sense, server-requested start/stop and bit-exact PCM delivery. Phone
capture itself can only be tested with real hardware.
