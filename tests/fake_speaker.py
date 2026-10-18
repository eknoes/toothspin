"""A simulated Sendspin speaker: counts the audio it gets, never makes a sound.

Used by the tests (connecting to a server's URL) and, run as a script, as a
speaker on the network that servers find via mDNS:

    python tests/fake_speaker.py "Test speaker" 8930
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
from dataclasses import dataclass, field, replace

from aiohttp import web
from aiosendspin.client import SendspinClient
from aiosendspin.client.listener import ClientListener
from aiosendspin.models.player import ClientHelloPlayerSupport, SupportedAudioFormat
from aiosendspin.models.types import AudioCodec, PlayerCommand, Roles
from aiosendspin.models.types import UndefinedField
from aiosendspin.noise import Identity, InMemoryClientPairingStore


@dataclass
class FakeSpeaker:
    name: str
    volume: int = 50
    muted: bool = False
    audio_bytes: int = 0
    streams_started: int = 0
    streams_ended: int = 0
    volumes: list[int] = field(default_factory=list)
    show_metadata: bool = False
    """Like a speaker with a display: takes the metadata role."""
    titles: list[str | None] = field(default_factory=list)
    client: SendspinClient | None = None

    async def build(self) -> SendspinClient:
        # Like most speakers set up for a home: plays for servers it isn't paired with.
        store = InMemoryClientPairingStore()
        config = await store.get_pairing_config()
        await store.store_pairing_config(replace(config, unpaired_access_enabled=True))
        self.client = SendspinClient(
            identity=Identity.generate(),
            client_name=self.name,
            roles=[Roles.PLAYER, Roles.METADATA] if self.show_metadata else [Roles.PLAYER],
            pairing_store=store,
            player_support=ClientHelloPlayerSupport(
                supported_formats=[
                    SupportedAudioFormat(
                        codec=AudioCodec.PCM, sample_rate=48000, bit_depth=16, channels=2
                    )
                ],
                buffer_capacity=1_000_000,
                supported_commands=[PlayerCommand.VOLUME, PlayerCommand.MUTE],
            ),
            initial_volume=self.volume,
        )
        self.client.add_audio_chunk_listener(self._on_audio)
        self.client.add_stream_start_listener(self._on_stream_start)
        self.client.add_stream_end_listener(self._on_stream_end)
        self.client.add_server_command_listener(self._on_command)
        self.client.add_metadata_listener(self._on_metadata)
        return self.client

    @property
    def client_id(self) -> str:
        assert self.client is not None
        return self.client.identity.peer_id

    def _on_metadata(self, payload) -> None:  # noqa: ANN001
        metadata = payload.metadata
        if metadata is not None and not isinstance(metadata.title, UndefinedField):
            self.titles.append(metadata.title)

    def _on_stream_start(self, _message: object) -> None:
        self.streams_started += 1

    def _on_stream_end(self, _roles: object) -> None:
        self.streams_ended += 1

    def _on_audio(self, _timestamp_us: int, data: bytes, _fmt: object, _send_ahead: object) -> None:
        self.audio_bytes += len(data)

    def _on_command(self, payload) -> None:  # noqa: ANN001
        if payload.player is None:
            return
        if payload.player.command is PlayerCommand.VOLUME and payload.player.volume is not None:
            self.volume = payload.player.volume
            self.volumes.append(self.volume)
        elif payload.player.command is PlayerCommand.MUTE and payload.player.mute is not None:
            self.muted = payload.player.mute
        asyncio.ensure_future(self._report())

    async def _report(self) -> None:
        assert self.client is not None
        with contextlib.suppress(RuntimeError):
            await self.client.send_player_state(available=True, volume=self.volume, muted=self.muted)


async def _serve(name: str, port: int) -> None:
    """Advertise via mDNS and accept connections from servers, like a real speaker."""
    speaker = FakeSpeaker(name)
    client = await speaker.build()

    async def on_connection(ws: web.WebSocketResponse) -> None:
        await client.attach_websocket(ws)
        done = asyncio.Event()
        remove = client.add_disconnect_listener(done.set)
        await done.wait()
        remove()

    listener = ClientListener(
        client_id=speaker.client_id, on_connection=on_connection, port=port, client_name=name
    )
    await listener.start()
    print(f"{name} listening on {port}", flush=True)
    while True:
        await asyncio.sleep(5)
        print(f"{name}: {speaker.audio_bytes} bytes, volume {speaker.volume}", flush=True)


if __name__ == "__main__":
    asyncio.run(_serve(sys.argv[1], int(sys.argv[2])))
