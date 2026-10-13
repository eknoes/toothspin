import asyncio
from pathlib import Path

from aiosendspin.models.types import AudioCodec

from sendspin_bluetooth import receivers as receivers_module
from sendspin_bluetooth.bluez import BluetoothDevice
from sendspin_bluetooth.receivers import Receivers


class FakeBluetooth:
    def __init__(self) -> None:
        self.paired: list[BluetoothDevice] = []

    def devices(self) -> list[BluetoothDevice]:
        return self.paired


def _device(address: str, name: str) -> BluetoothDevice:
    return BluetoothDevice(address, name, paired=True, trusted=True, connected=True)


def test_one_receiver_per_paired_phone(tmp_path: Path, monkeypatch) -> None:
    async def idle(source, capture) -> None:
        await asyncio.Event().wait()

    monkeypatch.setattr(receivers_module, "_run", idle)

    async def scenario() -> None:
        bluetooth = FakeBluetooth()
        receivers = Receivers(
            bluetooth, tmp_path, "ws://127.0.0.1:1/sendspin", AudioCodec.PCM,  # type: ignore[arg-type]
            "{device} (Bluetooth)",
        )
        bluetooth.paired = [_device("AA:AA:AA:AA:AA:AA", "Pixel"), _device("BB:BB:BB:BB:BB:BB", "iPhone")]
        await receivers.sync()

        pixel, iphone = receivers.get("aa:aa:aa:aa:aa:aa"), receivers.get("BB:BB:BB:BB:BB:BB")
        assert pixel and iphone
        assert pixel.source.status().name == "Pixel (Bluetooth)"
        # Separate Sendspin identities, so Music Assistant sees separate inputs.
        assert pixel.source.client.identity.peer_id != iphone.source.client.identity.peer_id
        assert (tmp_path / "devices" / "AA_AA_AA_AA_AA_AA" / "identity.json").exists()

        bluetooth.paired = bluetooth.paired[1:]
        await receivers.sync()
        assert receivers.get("AA:AA:AA:AA:AA:AA") is None
        assert not (tmp_path / "devices" / "AA_AA_AA_AA_AA_AA").exists()
        assert receivers.get("BB:BB:BB:BB:BB:BB") is iphone

        await receivers.close()

    asyncio.run(scenario())
