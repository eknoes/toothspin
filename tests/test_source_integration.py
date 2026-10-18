"""SendspinSource against an in-process aiosendspin server (the library MA runs).

Pairing uses a pre-staged pairing PSK, the same shortcut upstream's own
end-to-end tests take, so no PIN entry is needed.
"""

import asyncio
from pathlib import Path
from typing import Any

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer
from aiosendspin.models.types import SignalState
from aiosendspin.noise.keys import Identity, generate_psk, psk_id_for
from aiosendspin.noise.trust_store import InMemoryServerPairingStore, PairingPsk
from aiosendspin.server.roles.source.events import (
    SourceSignalChangedEvent,
    SourceStreamStartedEvent,
)
from aiosendspin.server.server import SendspinServer

from toothspin.pipewire import PcmFormat
from toothspin.source import SendspinSource


async def _until(predicate, timeout: float = 10.0) -> None:  # noqa: ANN001
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.02)


def _tone(fmt: PcmFormat, ms: int, value: int) -> bytes:
    frames = fmt.sample_rate * ms // 1000
    return value.to_bytes(2, "little", signed=True) * fmt.channels * frames


async def _push(source: SendspinSource, fmt: PcmFormat, chunks: int, value: int) -> bytes:
    sent = b""
    for _ in range(chunks):
        chunk = _tone(fmt, 20, value)
        await source.push(chunk, fmt, source.client.now_us())
        sent += chunk
        await asyncio.sleep(0.02)
    return sent


@pytest.mark.timeout(60)
def test_streams_on_server_request(tmp_path: Path) -> None:
    asyncio.run(_scenario(tmp_path))


async def _scenario(tmp_path: Path) -> None:
    server_store = InMemoryServerPairingStore()
    server = SendspinServer(
        loop=asyncio.get_running_loop(),
        identity=Identity.generate(),
        server_name="test-server",
        pairing_store=server_store,
    )
    app = web.Application()
    app.router.add_get(SendspinServer.API_PATH, server.on_client_connect)
    test_server = TestServer(app)
    await test_server.start_server()
    url = f"ws://127.0.0.1:{test_server.port}{SendspinServer.API_PATH}"

    source = SendspinSource("BT test", url, tmp_path)
    await source.setup()
    psk = generate_psk()
    pairing = PairingPsk(psk_id=psk_id_for(psk), psk=psk)
    await source._store.set_pairing_psk(pairing)  # noqa: SLF001
    await server_store.stage_pairing_psk(source.client.identity.peer_id, pairing)

    events: list[Any] = []
    run_task = asyncio.create_task(source.run())
    try:
        client_id = source.client.identity.peer_id

        def source_role():  # noqa: ANN202
            client = server.get_client(client_id)
            if client is None or "source@v1" not in client.active_role_ids:
                return None
            return client.role("source@v1")

        # Pairing happens on first connect; the run loop reconnects as needed
        # until source@v1 is active on a long-term PSK.
        await _until(lambda: source_role() is not None, timeout=30)
        await _until(lambda: source.client.is_time_synchronized())
        await _until(lambda: source.status().paired, timeout=3)

        server_client = server.get_client(client_id)
        server_client.add_event_listener(lambda _c, e: events.append(e))

        # Line-sense reaches the server.
        source.set_signal(True)
        await _until(
            lambda: any(
                isinstance(e, SourceSignalChangedEvent) and e.signal is SignalState.PRESENT
                for e in events
            )
        )

        # Nothing is streamed until the server asks.
        fmt = PcmFormat(sample_rate=48000, channels=2)
        await _push(source, fmt, 5, 1000)
        assert not source.status().streaming

        source_role().request_start()
        await _until(lambda: source.status().streaming)
        await _until(lambda: [e for e in events if isinstance(e, SourceStreamStartedEvent)])
        started = [e for e in events if isinstance(e, SourceStreamStartedEvent)]
        assert started[0].handle is not None

        received = bytearray()

        async def drain(handle: Any) -> None:
            async for chunk, _ts in handle:
                received.extend(chunk)

        drain_task = asyncio.create_task(drain(started[0].handle))
        # The phone isn't playing yet: silence keeps the server's stream alive
        # (Music Assistant gives up on an input that stays mute for 5 s).
        await _until(lambda: len(received) >= 4 * 1920)
        assert not any(received)
        sent = await _push(source, fmt, 25, 1234)
        # Then the phone's audio follows and the silence stops. Where the
        # phone's first chunk overlaps the last silent one, the overlap is
        # trimmed rather than played twice: at most one chunk.
        await _until(lambda: len(bytes(received).lstrip(b"\0")) >= len(sent) - 3840)
        audio = bytes(received).lstrip(b"\0")
        assert audio == sent[len(sent) - len(audio):]

        # A codec renegotiation on the phone (new rate) ends the stream; only
        # the server may open the next one, in the new format.
        new_fmt = PcmFormat(sample_rate=44100, channels=2)
        await _push(source, new_fmt, 5, 500)
        await _until(lambda: not source.status().streaming)
        source_role().request_start()
        await _push(source, new_fmt, 5, 500)
        await _until(
            lambda: len([e for e in events if isinstance(e, SourceStreamStartedEvent)]) >= 2
        )
        restarted = [e for e in events if isinstance(e, SourceStreamStartedEvent)][-1]
        assert restarted.audio_format.sample_rate == 44100

        source_role().request_stop()
        await _until(lambda: not source.status().streaming)
        drain_task.cancel()

        # Stopping the service says goodbye with RESTART: the server keeps the
        # client around (warm) so Music Assistant re-requests the stream once
        # it reconnects, instead of forgetting it.
        run_task.cancel()
        await asyncio.gather(run_task, return_exceptions=True)
        await asyncio.sleep(0.2)
        assert server.get_client(client_id) is not None
    finally:
        run_task.cancel()
        await asyncio.gather(run_task, return_exceptions=True)
        await test_server.close()
        await server.close()
