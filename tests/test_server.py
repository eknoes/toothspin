"""ToothSpin's own Sendspin server, end to end with simulated speakers.

A phone's Sendspin source pairs with the server by itself, and the server is
driven through the same Music Assistant style commands the web UI uses.
"""

import asyncio
import socket
from pathlib import Path

import pytest

from fake_speaker import FakeSpeaker
from toothspin import speakers
from toothspin.backend import BackendError
from toothspin.pipewire import CAPTURE_FORMAT
from toothspin.server import ToothSpinServer, correct_drift
from toothspin.source import SendspinSource


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


async def _until(predicate, timeout: float = 10.0) -> None:  # noqa: ANN001
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.05)


@pytest.mark.timeout(90)
def test_plays_a_phone_on_grouped_speakers(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    # No mDNS in tests: speakers connect to the server's URL themselves.
    monkeypatch.setattr(
        "aiosendspin.server.server.SendspinServer._start_mdns_advertising",
        lambda *a, **k: asyncio.sleep(0),
    )
    monkeypatch.setattr(
        "aiosendspin.server.server.SendspinServer._start_mdns_discovery",
        lambda *a, **k: asyncio.sleep(0),
    )
    asyncio.run(_scenario(tmp_path))


async def _scenario(tmp_path: Path) -> None:
    server = ToothSpinServer(tmp_path, "ToothSpin test", port=_free_port())
    await server.start()
    server_task = asyncio.create_task(server.run())

    source = SendspinSource("Pixel (Bluetooth)", server.url, tmp_path / "phone")
    await source.setup()
    await server.pair_local(source)
    source_task = asyncio.create_task(source.run())

    kitchen, living = FakeSpeaker("Kitchen", volume=80), FakeSpeaker("Living room", volume=30)
    for speaker in (kitchen, living):
        await (await speaker.build()).connect(server.url)

    tasks = [server_task, source_task]
    try:
        await _until(lambda: source.status().paired and source.status().connected)
        await _until(lambda: len(server.players) == 2)
        uri = speakers.source_uri(source.client.identity.peer_id)
        listed = {s.name: s for s in speakers.speakers(server.players)}
        assert listed["Kitchen"].playing_uri is None
        assert listed["Kitchen"].can_group_with == {living.client_id}

        # Turning the kitchen on: the phone is asked for audio and it arrives.
        await speakers.toggle(server, uri, kitchen.client_id, True, start_volume=20)
        await _until(lambda: kitchen.volume == 20)  # left loud: turned down first
        await _until(lambda: source.status().requested)

        async def phone() -> None:
            chunk = b"\x10\x00" * CAPTURE_FORMAT.channels * 960  # 20 ms
            while True:
                await source.push(chunk, CAPTURE_FORMAT, source.client.now_us())
                await asyncio.sleep(0.02)

        tasks.append(asyncio.create_task(phone()))
        await _until(lambda: kitchen.audio_bytes > 0)

        # Adding the living room groups it with the kitchen; both get audio.
        await speakers.toggle(server, uri, living.client_id, True, start_volume=100)
        await _until(lambda: living.audio_bytes > 0)
        listed = {s.name: s for s in speakers.speakers(server.players)}
        assert listed["Living room"].synced_to == kitchen.client_id
        assert set(listed["Kitchen"].members) == {kitchen.client_id, living.client_id}
        assert listed["Kitchen"].group_volume == 25  # (20 + 30) / 2

        # Group volume redistributes, single volume and mute go to one speaker.
        await server.call("players/cmd/group_volume", player_id=kitchen.client_id, volume_level=45)
        await _until(lambda: (kitchen.volume, living.volume) == (40, 50))
        await server.call("players/cmd/volume_mute", player_id=living.client_id, muted=True)
        await _until(lambda: living.muted)

        # Moving to the living room alone stops the kitchen.
        await speakers.move(server, uri, living.client_id)
        listed = {s.name: s for s in speakers.speakers(server.players)}
        assert listed["Kitchen"].playing_uri is None
        assert listed["Living room"].playing_uri == uri and not listed["Living room"].members
        received = kitchen.audio_bytes
        await asyncio.sleep(0.5)
        assert kitchen.audio_bytes == received

        # Turning the last speaker off asks the phone to stop.
        await speakers.toggle(server, uri, living.client_id, False)
        await _until(lambda: not source.status().requested)

        with pytest.raises(BackendError):
            await server.call("player_queues/play_media", queue_id=kitchen.client_id,
                              media="spotify://track/1")
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for speaker in (kitchen, living):
            if speaker.client:
                await speaker.client.disconnect()


def test_drift_correction_drops_or_repeats_one_frame() -> None:
    pcm = bytes(range(8)) * 4  # 8 frames of 4 bytes
    assert correct_drift(pcm, 4, 100_000, 100_000) == pcm
    assert correct_drift(pcm, 4, 100_000, 130_000) == pcm[:-4]  # delay grew: drop
    assert correct_drift(pcm, 4, 100_000, 70_000) == pcm + pcm[-4:]  # shrank: repeat


def test_start_retries_while_the_network_is_down(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    import errno

    from aiosendspin.server import SendspinServer

    from toothspin import server as server_module
    from toothspin.server import ToothSpinServer

    attempts: list[int] = []

    async def start_server(self, **kwargs) -> None:  # noqa: ANN001, ANN003
        attempts.append(1)
        if len(attempts) < 3:
            raise OSError(errno.ENODEV, "No such device")

    monkeypatch.setattr(SendspinServer, "start_server", start_server)
    monkeypatch.setattr(server_module, "START_RETRY_S", 0.01)

    async def scenario() -> None:
        server = ToothSpinServer(tmp_path, "ToothSpin", port=0)
        await server.start()
        assert server.connected
        assert len(attempts) == 3

    asyncio.run(scenario())


def test_start_gives_up_when_the_port_is_taken(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    import errno

    import pytest
    from aiosendspin.server import SendspinServer

    from toothspin.server import ToothSpinServer

    async def start_server(self, **kwargs) -> None:  # noqa: ANN001, ANN003
        raise OSError(errno.EADDRINUSE, "Address in use")

    monkeypatch.setattr(SendspinServer, "start_server", start_server)
    with pytest.raises(OSError):
        asyncio.run(ToothSpinServer(tmp_path, "ToothSpin", port=0).start())
