# ToothSpin

**Bluetooth audio input for Sendspin and Music Assistant.** Stream any
phone over Bluetooth into Music Assistant.

<img src="assets/toothspin.svg" width="96" alt="ToothSpin icon">

Turns a Bluetooth dongle into a speaker that phones can pair with. Whatever
a phone plays shows up in Music Assistant as a live input (a Sendspin
**source**), which you can play on any player or group.

```
Phone ─A2DP─> bluetoothd (host) ─> PipeWire/WirePlumber (core's user session)
      ─pw-record over the PipeWire socket─> toothspin (rootless podman)
      ─Sendspin source@v1 over WebSocket─> Music Assistant (sendspin_source provider)
```

Needs Music Assistant **2.10.6 or newer** (it ships the `sendspin_source`
provider; the service pins `aiosendspin==9.1.1` to match). See
[CLAUDE.md](CLAUDE.md) for background and scope: one dongle; every paired
phone becomes its own Live Input in Music Assistant.

## Setup

The container image is self-contained (its own PipeWire, ~120 MB). The host
only needs:

- **BlueZ** (`bluetoothd`) running with the USB dongle. Recommended: our
  [main.conf](deploy/bluetooth/main.conf), so phones see a speaker and BlueZ
  doesn't reconnect phones by itself.
- **No other Bluetooth audio stack** on the host (a desktop PipeWire or
  PulseAudio with Bluetooth would compete for the phones).

### Any Linux host (Docker / Podman)

```bash
docker build -t toothspin .
docker run -d --name toothspin --restart unless-stopped \
  --network host \
  -v /run/dbus/system_bus_socket:/run/dbus/system_bus_socket \
  -v toothspin-data:/data \
  --security-opt label=disable \
  -e MA_URL=http://<music-assistant>:8095 -e MA_TOKEN=<token> \
  toothspin
```

`--network host` is for finding Music Assistant via mDNS and the web UI on
:8080; `label=disable` only matters on SELinux hosts. Rootless Podman also
needs `--userns keep-id`, so D-Bus sees your own uid.

### The CoreOS VM

On the VM ([deploy/coreos](deploy/coreos/)), as `core`, from a copy of this
repo:

1. Layer BlueZ (once): `sudo rpm-ostree install --apply-live bluez usbutils`
2. Install our BlueZ config: `deploy/bluetooth/install.sh`
3. Build and start the rootless Quadlet unit: `deploy/service/install.sh`
   (it also masks a host PipeWire, if one is installed).

The web UI is then on `http://<host>:8080/`. It has no login — keep it on the
home LAN.

### Configuration

Optional, in `~/.config/toothspin.env` (then
`systemctl --user restart toothspin`):

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
2. On the phone, connect to `BT_NAME`. Pairing closes again once a phone has
   paired; outside that window pairing is refused.

Connections always start from the receiver: press **Connect** on the
phone's card. A phone trying to connect on its own is refused, and the
receiver doesn't reconnect by itself after the link drops.

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

## Releasing

CI ([.github/workflows/ci.yml](.github/workflows/ci.yml)) runs the tests and
builds the amd64/arm64 image on every push and pull request. Pushes to
`main` publish `ghcr.io/<owner>/toothspin:edge`. To release:

1. Bump `version` in `pyproject.toml` and commit.
2. Tag and push: `git tag v0.2.0 && git push origin v0.2.0`.

The tag must match the version; CI then publishes
`ghcr.io/<owner>/toothspin:0.2.0` (and `:0.2`) and creates a GitHub release
with generated notes.

## License

GPL-3.0-or-later, see [LICENSE](LICENSE). Third-party components in the
container image and where to get their source: [LICENSING.md](LICENSING.md).
