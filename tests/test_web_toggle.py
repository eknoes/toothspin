import asyncio
from types import SimpleNamespace

from aiohttp.test_utils import TestClient, TestServer

from toothspin import speakers
from toothspin.web import create_app

PHONE = "AA:BB:CC:00:00:01"


def test_quick_clicks_on_a_speaker_only_send_the_latest(monkeypatch) -> None:
    calls: list[bool] = []
    release = asyncio.Event()

    async def slow_toggle(backend, uri, player_id, on, start_volume):  # noqa: ANN001, ARG001
        calls.append(on)
        if len(calls) == 1:
            await release.wait()  # Music Assistant hangs on the first

    monkeypatch.setattr(speakers, "toggle", slow_toggle)
    source = SimpleNamespace(client=SimpleNamespace(identity=SimpleNamespace(peer_id="phone")))
    receivers = SimpleNamespace(get=lambda address: SimpleNamespace(source=source))
    backend = SimpleNamespace(connected=True, players=[])

    async def scenario() -> list[dict]:
        app = create_app(None, receivers, 120, backend)  # type: ignore[arg-type]
        async with TestClient(TestServer(app)) as client:
            async def click(on: bool) -> dict:
                response = await client.post(
                    f"/api/speakers/{PHONE}/toggle", json={"player_id": "kitchen", "on": on}
                )
                return await response.json()

            first = asyncio.create_task(click(True))
            await asyncio.sleep(0.1)
            second = asyncio.create_task(click(False))
            await asyncio.sleep(0.1)
            third = asyncio.create_task(click(True))
            await asyncio.sleep(0.1)
            release.set()
            return [await first, await second, await third]

    replies = asyncio.run(scenario())
    assert calls == [True, True]
    assert replies[1] == {"ok": True, "superseded": True}
    assert replies[0]["ok"] and replies[2]["ok"]


def test_a_timeout_says_what_happened(monkeypatch) -> None:
    async def hanging_toggle(*_args) -> None:  # noqa: ANN002
        raise TimeoutError

    monkeypatch.setattr(speakers, "toggle", hanging_toggle)
    source = SimpleNamespace(client=SimpleNamespace(identity=SimpleNamespace(peer_id="phone")))
    receivers = SimpleNamespace(get=lambda address: SimpleNamespace(source=source))

    async def scenario() -> tuple[int, dict]:
        app = create_app(None, receivers, 120, SimpleNamespace(connected=True, players=[]))  # type: ignore[arg-type]
        async with TestClient(TestServer(app)) as client:
            response = await client.post(f"/api/speakers/{PHONE}/toggle",
                                         json={"player_id": "kitchen", "on": True})
            return response.status, await response.json()

    status, body = asyncio.run(scenario())
    assert status == 502 and "didn't answer in time" in body["error"]
