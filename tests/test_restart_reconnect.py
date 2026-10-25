import asyncio
from types import SimpleNamespace

from toothspin import __main__ as main


class FakeBluetooth:
    def __init__(self, connected: set[str]) -> None:
        self.connected = connected
        self.calls: list[str] = []

    def devices(self) -> list[SimpleNamespace]:
        return [SimpleNamespace(address=a, name=a, connected=a in self.connected)
                for a in ("AA:AA:AA:AA:AA:AA", "BB:BB:BB:BB:BB:BB")]

    async def connect_device(self, address: str) -> None:
        self.calls.append(address)

    def transport(self, address: str) -> None:
        return None

    async def connect_audio(self, address: str) -> None:
        self.calls.append(f"audio {address}")


def test_phones_connected_at_shutdown_are_reconnected_once(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "RECONNECT_DELAY_S", 0)
    path = tmp_path / "reconnect.json"
    main._remember_connected(FakeBluetooth({"AA:AA:AA:AA:AA:AA"}), path)  # type: ignore[arg-type]

    after_restart = FakeBluetooth(set())
    asyncio.run(main._reconnect_after_restart(after_restart, path))  # type: ignore[arg-type]
    assert after_restart.calls == ["AA:AA:AA:AA:AA:AA"]
    assert not path.exists()  # only right after that restart
    asyncio.run(main._reconnect_after_restart(after_restart, path))  # type: ignore[arg-type]
    assert after_restart.calls == ["AA:AA:AA:AA:AA:AA"]


def test_phones_still_connected_get_their_audio_back(tmp_path, monkeypatch) -> None:
    # BlueZ ends a phone's audio with ToothSpin's audio stack, not always the connection.
    monkeypatch.setattr(main, "RECONNECT_DELAY_S", 0)
    path = tmp_path / "reconnect.json"
    both = {"AA:AA:AA:AA:AA:AA", "BB:BB:BB:BB:BB:BB"}
    main._remember_connected(FakeBluetooth(both), path)  # type: ignore[arg-type]

    after_restart = FakeBluetooth({"BB:BB:BB:BB:BB:BB"})
    asyncio.run(main._reconnect_after_restart(after_restart, path))  # type: ignore[arg-type]
    assert after_restart.calls == ["AA:AA:AA:AA:AA:AA", "audio BB:BB:BB:BB:BB:BB"]
