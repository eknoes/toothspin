import asyncio
import os
import stat
from pathlib import Path

from toothspin import ha_audio

# `pactl list modules short` on Home Assistant OS with a phone held by PulseAudio.
MODULES = (
    "0\tmodule-device-restore\t\n"
    "6\tmodule-bluetooth-discover\t\n"
    "7\tmodule-bluez5-discover\t\n"
    "18\tmodule-bluez5-device\tpath=/org/bluez/hci0/dev_34_39_16_5D_41_B9 autodetect_mtu=0\n"
    "20\tmodule-native-protocol-unix\tsocket=/data/external/pulse.sock\n"
)


def _fake_pactl(tmp_path: Path, monkeypatch) -> Path:
    calls = tmp_path / "calls"
    script = tmp_path / "bin" / "pactl"
    script.parent.mkdir()
    script.write_text(
        "#!/bin/sh\n"
        f'echo "$@" >> {calls}\n'
        f'if [ "$2" = list ]; then printf %s "$MODULES"; fi\n'
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{script.parent}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("MODULES", MODULES)
    return calls


def test_finds_only_the_bluetooth_modules(tmp_path, monkeypatch) -> None:
    _fake_pactl(tmp_path, monkeypatch)
    modules = asyncio.run(ha_audio.bluetooth_modules(tmp_path / "pulse.sock"))
    assert [name for _, name, _ in modules] == [
        "module-bluetooth-discover", "module-bluez5-discover", "module-bluez5-device",
    ]


def test_release_unloads_discovery_first_and_names_the_held_phones(tmp_path, monkeypatch) -> None:
    calls = _fake_pactl(tmp_path, monkeypatch)
    held = asyncio.run(ha_audio.release(tmp_path / "pulse.sock"))
    assert held == ["34:39:16:5D:41:B9"]
    unloads = [line.split()[-1] for line in calls.read_text().splitlines() if "unload-module" in line]
    assert unloads == ["6", "7", "18"]
    assert all(f"--server=unix:{tmp_path / 'pulse.sock'}" in line for line in calls.read_text().splitlines())


def test_available_needs_the_socket(tmp_path, monkeypatch) -> None:
    _fake_pactl(tmp_path, monkeypatch)
    assert not ha_audio.available(tmp_path / "missing.sock")
    (tmp_path / "pulse.sock").touch()
    assert ha_audio.available(tmp_path / "pulse.sock")
