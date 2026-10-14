# Development

How ToothSpin is built: [technical overview](https://eknoes.github.io/toothspin/overview.html)
(source in [docs/](docs/)).

## Layout

- [src/toothspin](src/toothspin/): the service. It finds each phone's
  PipeWire node, captures it with `pw-record` and feeds an aiosendspin
  `SourceCapture`; it also runs the BlueZ pairing agent and the web UI.
  Speakers are controlled through a backend (`backend.py`): Music Assistant
  (`ma.py`, with `ma_pairing.py` pairing inputs through its API) or
  ToothSpin's own Sendspin server (`server.py`, standalone mode), both
  offering the same slice of Music Assistant's player API.
- [deploy/](deploy/): PipeWire/WirePlumber config baked into the image, the
  BlueZ config, the SELinux policy, the Quadlet unit and the CoreOS config.
- [toothspin/](toothspin/): the Home Assistant App, with
  [repository.yaml](repository.yaml) at the root.

## Tests

```bash
python -m venv .venv && .venv/bin/pip install -e '.[test]'
.venv/bin/pytest
```

`tests/test_source_integration.py` runs the source client against an
in-process aiosendspin server (the library Music Assistant uses): pairing,
line-sense, server-requested start/stop and bit-exact PCM delivery. Phone
capture itself can only be tested with real hardware.

## Trying a change on real hardware

On a machine with BlueZ and the dongle, from a checkout:

```bash
deploy/service/install.sh
```

It builds the image, loads the SELinux policy where needed and runs the
build as a rootless Quadlet unit (a drop-in points the unit at the local
image instead of the release). Logs: `journalctl --user -u toothspin`.

For standalone mode, build the server image and point the unit at it with
another drop-in, `~/.config/containers/systemd/toothspin.container.d/standalone.conf`:

```bash
podman build --build-arg EXTRAS=server -t localhost/toothspin:server .
```

```ini
[Container]
Image=localhost/toothspin:server
Environment=MODE=standalone
```

`tests/fake_speaker.py "Test speaker" 8930` runs a simulated Sendspin
speaker that servers find via mDNS: it counts the audio it gets and never
makes a sound, handy to try grouping without waking the house.

## Rules of thumb

- **aiosendspin follows Music Assistant.** `source@v1` is young and still
  changing. Keep `aiosendspin` pinned to the version the supported Music
  Assistant ships (`aiosendspin[server]==` in its `pyproject.toml`; 9.1.1
  for 2.10.6): 10.x renamed the `client_stream/*` messages, so a newer
  client breaks against an older server. Bump both together.
- **One self-contained image** for Docker, Podman and the Home Assistant
  App. Nothing on the host beyond `bluetoothd`.
- **The App's web UI sits behind ingress:** relative URLs only, and the
  ingress port only answers the Supervisor's proxy (172.30.32.2).
- **Build for what exists:** one dongle, the devices we have.
- Atomic commits with short [conventional](https://www.conventionalcommits.org)
  messages.

## Releasing

CI ([.github/workflows/ci.yml](.github/workflows/ci.yml)) runs the tests,
lints the App and builds the amd64/arm64 image on every push and pull
request. Pushes to `main` publish `ghcr.io/eknoes/toothspin:edge`. To
release:

1. Bump `version` in `pyproject.toml` and in
   [toothspin/config.yaml](toothspin/config.yaml) (the image tag the App
   installs; CI checks both match), and commit.
2. Tag and push: `git tag v0.2.0 && git push origin v0.2.0`.

CI then publishes `ghcr.io/eknoes/toothspin:0.2.0` (plus `:0.2` and
`:latest`), the server image for standalone mode as `0.2.0-server` (plus
`:0.2-server` and `:latest-server`), and creates a GitHub release. Its notes are generated from the
commits since the previous release ([cliff.toml](cliff.toml)): `feat`,
`fix`, `perf`, `build` and `docs` commits, grouped by type, so write their
subjects for users. Preview them with `git cliff --unreleased`.

## Vulnerabilities and SBOM

Every CI run generates SBOMs of the image (SPDX and CycloneDX, with syft)
and scans them with grype. High or critical vulnerabilities that have a fix
fail the build; all findings are listed in the run's summary. Releases
attach both SBOMs, and published images carry SBOM and provenance
attestations.

New vulnerabilities turn up after an image was built, so
[scan.yml](.github/workflows/scan.yml) rescans the latest release weekly. A
failed scan means it's time to release again: the rebuild picks up
Alpine's current packages. Dependabot proposes new Alpine releases and
action versions.
