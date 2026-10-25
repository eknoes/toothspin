import asyncio

from dbus_fast.errors import DBusError

from toothspin import covers as covers_module
from toothspin.bluez import BluetoothDevice, NowPlaying
from toothspin.covers import Covers

PHONE = "AA:BB:CC:DD:EE:FF"


class FakePhones:
    def __init__(self) -> None:
        self.connected = True
        self.port: int | None = 4097
        self.handle: str | None = "1000001"

    def devices(self) -> list[BluetoothDevice]:
        return [BluetoothDevice(PHONE, "Pixel", self.connected)]

    def cover_port(self, address: str) -> int | None:
        return self.port

    def now_playing(self, address: str) -> NowPlaying | None:
        return NowPlaying("playing", "Near Light", "Ólafur Arnalds", image_handle=self.handle)


class FakeObex:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.fail_fetch = False
        self.sessions = 0

    async def open(self, address: str, port: int) -> str:
        self.sessions += 1
        self.calls.append(f"open {address} {port}")
        return f"/session{self.sessions}"

    async def close(self, session: str) -> None:
        self.calls.append(f"close {session}")

    async def fetch(self, session: str, handle: str) -> bytes:
        self.calls.append(f"fetch {session} {handle}")
        if self.fail_fetch:
            raise DBusError("org.bluez.obex.Error.Failed", "Not Acceptable")
        return f"jpeg {handle}".encode()


def test_fetches_each_cover_once_per_session() -> None:
    phones, obex = FakePhones(), FakeObex()
    covers = Covers(phones, obex)

    async def scenario() -> None:
        assert covers.cover(PHONE) is None
        await covers.sync()
        assert covers.cover(PHONE) == ("1000001", b"jpeg 1000001")
        await covers.sync()  # same track: nothing to fetch
        phones.handle = "1000002"
        await covers.sync()
        assert covers.cover(PHONE) == ("1000002", b"jpeg 1000002")
        phones.handle = "1000001"  # back to the first track: still known
        await covers.sync()
        assert covers.cover(PHONE) == ("1000001", b"jpeg 1000001")
        assert obex.calls == [
            f"open {PHONE} 4097", "fetch /session1 1000001", "fetch /session1 1000002",
        ]

        # Gone: its session is closed, and a new one starts afresh.
        phones.connected = False
        await covers.sync()
        assert covers.cover(PHONE) is None
        phones.connected = True
        await covers.sync()
        assert obex.calls[-3:] == ["close /session1", f"open {PHONE} 4097", "fetch /session2 1000001"]

    asyncio.run(scenario())


def test_no_session_for_phones_without_covers_or_tracks_without_one() -> None:
    phones, obex = FakePhones(), FakeObex()
    covers = Covers(phones, obex)
    phones.port = None
    asyncio.run(covers.sync())
    assert obex.calls == []

    phones.port, phones.handle = 4097, None
    asyncio.run(covers.sync())
    assert obex.calls == [f"open {PHONE} 4097"]
    assert covers.cover(PHONE) is None


def test_a_failed_cover_is_retried_later_in_a_new_session(monkeypatch) -> None:  # noqa: ANN001
    phones, obex = FakePhones(), FakeObex()
    covers = Covers(phones, obex)
    now = [100.0]
    monkeypatch.setattr(covers_module.time, "monotonic", lambda: now[0])

    async def scenario() -> None:
        obex.fail_fetch = True
        await covers.sync()
        assert covers.cover(PHONE) is None
        assert obex.calls[-1] == "close /session1"
        obex.fail_fetch = False
        await covers.sync()  # not right away
        assert obex.sessions == 1
        now[0] += covers_module.RETRY_S
        await covers.sync()
        assert covers.cover(PHONE) == ("1000001", b"jpeg 1000001")

    asyncio.run(scenario())
