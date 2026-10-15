import asyncio
from pathlib import Path

from aiosendspin.models.types import AudioCodec

from toothspin import receivers as receivers_module
from toothspin.bluez import BluetoothDevice
from toothspin.receivers import Receivers


class FakeBluetooth:
    def __init__(self) -> None:
        self.paired: list[BluetoothDevice] = []

    def devices(self) -> list[BluetoothDevice]:
        return self.paired


def _device(address: str, name: str) -> BluetoothDevice:
    return BluetoothDevice(address, name, connected=True)


def test_one_receiver_per_paired_phone(tmp_path: Path, monkeypatch) -> None:
    async def idle(source, capture, extra=None) -> None:
        await asyncio.Event().wait()

    monkeypatch.setattr(receivers_module, "_run", idle)

    async def scenario() -> None:
        bluetooth = FakeBluetooth()
        receivers = Receivers(
            bluetooth, tmp_path, "ws://127.0.0.1:1/sendspin", AudioCodec.PCM,  # type: ignore[arg-type]
            "{device} (Bluetooth)", "sendspin-bt",
        )
        bluetooth.paired = [_device("AA:AA:AA:AA:AA:AA", "Pixel"), _device("BB:BB:BB:BB:BB:BB", "iPhone")]
        await receivers.sync()

        pixel, iphone = receivers.get("aa:aa:aa:aa:aa:aa"), receivers.get("BB:BB:BB:BB:BB:BB")
        assert pixel and iphone
        assert pixel.source.status().name == "Pixel (Bluetooth)"
        # Separate Sendspin identities, so Music Assistant sees separate inputs.
        assert pixel.source.client.identity.peer_id != iphone.source.client.identity.peer_id
        assert (tmp_path / "devices" / "AA_AA_AA_AA_AA_AA" / "identity.json").exists()

        # A name chosen in the web UI sticks, and the client reconnects with it.
        await receivers.rename("bb:bb:bb:bb:bb:bb", "Kitchen phone")
        renamed = receivers.get("BB:BB:BB:BB:BB:BB")
        assert renamed is not iphone and renamed.source.status().name == "Kitchen phone"
        assert renamed.source.client.identity.peer_id == iphone.source.client.identity.peer_id
        iphone = renamed

        # A phone vanishing from BlueZ (e.g. bluetoothd restarting) only stops
        # its client: its identity and MA pairing survive.
        pixel_id = pixel.source.client.identity.peer_id
        paired = bluetooth.paired
        bluetooth.paired = paired[1:]
        await receivers.sync()
        assert receivers.get("AA:AA:AA:AA:AA:AA") is None
        assert (tmp_path / "devices" / "AA_AA_AA_AA_AA_AA" / "identity.json").exists()
        assert receivers.get("BB:BB:BB:BB:BB:BB") is iphone
        bluetooth.paired = paired
        await receivers.sync()
        assert receivers.get("AA:AA:AA:AA:AA:AA").source.client.identity.peer_id == pixel_id

        # Removing it in the web UI forgets the identity.
        bluetooth.paired = paired[1:]
        await receivers.forget("aa:aa:aa:aa:aa:aa")
        assert receivers.get("AA:AA:AA:AA:AA:AA") is None
        assert not (tmp_path / "devices" / "AA_AA_AA_AA_AA_AA").exists()

        await receivers.close()

    asyncio.run(scenario())


def test_hidden_speakers_are_kept_per_phone(tmp_path: Path, monkeypatch) -> None:
    async def idle(source, capture, extra=None) -> None:
        await asyncio.Event().wait()

    monkeypatch.setattr(receivers_module, "_run", idle)

    async def scenario() -> None:
        bluetooth = FakeBluetooth()
        bluetooth.paired = [_device("AA:AA:AA:AA:AA:AA", "Pixel"), _device("BB:BB:BB:BB:BB:BB", "iPhone")]
        receivers = Receivers(
            bluetooth, tmp_path, "ws://127.0.0.1:1/sendspin", AudioCodec.PCM,  # type: ignore[arg-type]
            "{device} (Bluetooth)", "sendspin-bt",
        )
        await receivers.sync()

        receivers.set_speaker_hidden("aa:aa:aa:aa:aa:aa", "kitchen", True)
        receivers.set_speaker_hidden("AA:AA:AA:AA:AA:AA", "office", True)
        assert receivers.hidden_speakers("AA:AA:AA:AA:AA:AA") == ["kitchen", "office"]
        assert receivers.hidden_speakers("BB:BB:BB:BB:BB:BB") == []  # per phone

        # Renaming used to overwrite the settings file.
        await receivers.rename("AA:AA:AA:AA:AA:AA", "Work phone")
        assert receivers.hidden_speakers("AA:AA:AA:AA:AA:AA") == ["kitchen", "office"]

        receivers.set_speaker_hidden("AA:AA:AA:AA:AA:AA", "kitchen", False)
        assert receivers.hidden_speakers("AA:AA:AA:AA:AA:AA") == ["office"]

        # Survives a restart.
        await receivers.close()
        again = Receivers(
            bluetooth, tmp_path, "ws://127.0.0.1:1/sendspin", AudioCodec.PCM,  # type: ignore[arg-type]
            "{device} (Bluetooth)", "sendspin-bt",
        )
        await again.sync()
        assert again.hidden_speakers("AA:AA:AA:AA:AA:AA") == ["office"]
        assert again.get("AA:AA:AA:AA:AA:AA").source.status().name == "Work phone"
        await again.close()

    asyncio.run(scenario())
