"""ToothSpin's own Sendspin server, for setups without Music Assistant.

It finds Sendspin speakers via mDNS, connects to them and plays the phones'
inputs on them, synchronised and grouped. Only Sendspin speakers, and only the
phones' inputs: nothing else to play.

The phones' Sendspin sources connect to it over localhost exactly as they
would to Music Assistant, paired automatically. Towards the rest of ToothSpin
it speaks the same slice of Music Assistant's player API as ``ma.py`` (see
``backend.py``), so the web UI and the volume sync don't know the difference.
"""

from __future__ import annotations

import asyncio
import errno
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from aiosendspin.models.types import has_role_family
from aiosendspin.noise import FileServerPairingStore
from aiosendspin.noise.keys import generate_psk, psk_id_for
from aiosendspin.noise.trust_store import PairingPsk, StagedPairingPsk
from aiosendspin.server import (
    ClientAddedEvent,
    ClientConnectedEvent,
    SendspinServer,
    SourceStreamStartedEvent,
)
from aiosendspin.server.push_stream import StreamStoppedError
from aiosendspin.server.roles.metadata.state import Metadata

from .backend import BackendError
from .source import _load_identity

if TYPE_CHECKING:
    from aiosendspin.server import AudioFormat, PushStream, SendspinClient, SendspinGroup
    from aiosendspin.server.roles.source.stream import SourceStream

    from .bluez import NowPlaying
    from .source import SendspinSource

logger = logging.getLogger(__name__)

SOURCE_PREFIX = "sendspin_source://audio_source/"
# Speakers connected to another server (e.g. Music Assistant) only switch over
# when asked to play; wait this long for them.
CLAIM_TIMEOUT_S = 10.0
# Right after boot, mDNS can fail until the network is up, and aiosendspin
# 9.1.1 then shuts the whole server down: start again after this long,
# doubling up to the maximum.
START_RETRY_S = 2.0
START_RETRY_MAX_S = 60.0
# How often to look for new track info from the phones.
METADATA_S = 1.0
# How aiosendspin 9.1.1 notes a speaker that doesn't report its timing
# (min_buffer_ms and others): it then assumes a buffer of 1000 ms.
_NO_TIMING_REPORTED = "initial client/state omitted required player timing fields"
# Keep the delay from phone to speakers within this of where it started:
# phone and speakers run on slightly different clocks.
DRIFT_TOLERANCE_US = 20_000


@dataclass(eq=False, slots=True)
class _Route:
    """A group playing an input, with its stream and drift correction state."""

    group: SendspinGroup
    source_id: str
    stream: PushStream | None = None
    target_delay_us: int | None = None
    """Phone-to-speaker delay when the stream started; drift is corrected towards it."""
    delay_us: int | None = None


@dataclass(slots=True)
class _Session:
    """A speaker playing a phone: what went wrong on the way to it."""

    name: str
    started: float
    late_chunks: int = 0
    late_times: int = 0


@dataclass(slots=True)
class _Feed:
    """An input being streamed, fanned out to the groups playing it."""

    routes: list[_Route] = field(default_factory=list)
    task: asyncio.Task[None] | None = None


class ToothSpinServer:
    def __init__(
        self,
        data_dir: Path,
        name: str,
        port: int = 8927,
        speaker_buffer_ms: int | None = None,
        now_playing: Callable[[str], NowPlaying | None] | None = None,
    ) -> None:
        self._data_dir = data_dir / "server"
        self._name = name
        self._port = port
        # The buffer for speakers that don't report their own; None keeps
        # aiosendspin's 1000 ms. Less starts playback sooner, too little drops out.
        self._speaker_buffer_ms = speaker_buffer_ms
        # What a phone plays (AVRCP), by its source's client id: shown on
        # speakers with a display.
        self._now_playing = now_playing
        # Speakers playing a phone now, by client id.
        self._sessions: dict[str, _Session] = {}
        self._server: SendspinServer | None = None
        self._store: FileServerPairingStore | None = None
        self._feeds: dict[str, _Feed] = {}
        self._started = asyncio.Event()

    @property
    def url(self) -> str:
        """Where the phones' sources connect."""
        return f"ws://127.0.0.1:{self._port}{SendspinServer.API_PATH}"

    @property
    def connected(self) -> bool:
        return self._started.is_set()

    @property
    def server_id(self) -> str:
        assert self._server is not None
        return self._server.id

    async def start(self) -> None:
        self._data_dir.mkdir(parents=True, exist_ok=True)
        identity = _load_identity(self._data_dir / "identity.json")
        self._store = await FileServerPairingStore.open(self._data_dir / "pairing-store.json")
        self._server = SendspinServer(
            loop=asyncio.get_running_loop(),
            identity=identity,
            server_name=self._name,
            pairing_store=self._store,
            # Many speakers (e.g. ESPHome's) still speak Sendspin unencrypted.
            allow_unencrypted=True,
        )
        self._server.add_event_listener(self._on_server_event)
        delay = START_RETRY_S
        while True:
            try:
                await self._server.start_server(port=self._port)
                break
            except OSError as err:
                if err.errno == errno.EADDRINUSE:
                    raise
                logger.warning("Sendspin server couldn't start (%s); retrying in %.0fs", err, delay)
                await asyncio.sleep(delay)
                delay = min(delay * 2, START_RETRY_MAX_S)
        self._started.set()
        logger.info("Sendspin server %s listening on port %d", self._name, self._port)

    async def run(self) -> None:
        """Serve until cancelled, keeping the speakers' track info current."""
        try:
            while True:
                self._update_metadata()
                self._track_sessions()
                await asyncio.sleep(METADATA_S)
        finally:
            for feed in self._feeds.values():
                if feed.task:
                    feed.task.cancel()
            if self._server is not None:
                await self._server.close()

    async def refresh(self) -> None:
        """State is local and always current."""

    async def pair_local(self, source: SendspinSource) -> None:
        """Pair one of our own phone sources, which a user can't do by hand here."""
        assert self._store is not None
        client_id = source.client.identity.peer_id
        if await self._store.record_by_client_id(client_id) and await source.paired_with(
            self.server_id
        ):
            return
        psk = generate_psk()
        await source.accept_pairing(PairingPsk(psk_id=psk_id_for(psk), psk=psk))
        await self._store.stage_pairing_psk(client_id, StagedPairingPsk(psk_id_for(psk), psk))

    async def forget(self, client_id: str) -> None:
        """A phone was removed: drop its input and pairing."""
        assert self._server is not None and self._store is not None
        await self._server.remove_client(client_id)
        await self._store.remove_record(client_id)

    # --- Music Assistant's player API ---

    @property
    def players(self) -> list[dict[str, Any]]:
        if self._server is None:
            return []
        return [self._player(c) for c in self._server.clients if _is_player(c)]

    def _player(self, client: SendspinClient) -> dict[str, Any]:
        members = [c for c in client.group.clients if _is_player(c)]
        leader = members[0] if members else client
        route = self._route(client.group)
        role = _role(client, "player")
        group_role = client.group.group_role("player")
        return {
            "player_id": client.client_id,
            "name": client.name,
            "type": "player",
            "provider": "toothspin",
            # Speakers connected to another server can be claimed for playback.
            "available": client.is_connected or client.info_or_none is not None,
            "can_group_with": [
                c.client_id for c in self._server.clients  # type: ignore[union-attr]
                if _is_player(c) and c is not client
            ],
            "playback_state": "playing" if route else "idle",
            "active_source": SOURCE_PREFIX + route.source_id if route else None,
            "synced_to": leader.client_id if leader is not client else None,
            "group_members": [m.client_id for m in members]
            if leader is client and len(members) > 1
            else [],
            "volume_level": getattr(role, "volume", None),
            "group_volume": group_role.get_group_volume() if group_role else None,
            "volume_muted": bool(getattr(role, "muted", False)),
            "volume_control": "internal" if role else "none",
            "mute_control": "internal" if role else "none",
        }

    async def call(self, command: str, **args: Any) -> Any:
        if command == "player_queues/play_media":
            await self._play(await self._client(args["queue_id"]), args["media"])
        elif command == "players/cmd/stop":
            await self._stop(self._known(args["player_id"]).group)
        elif command == "players/cmd/set_members":
            target = await self._client(args["target_player"])
            for player_id in args.get("player_ids_to_remove") or ():
                await self._known(player_id).ungroup()
            for player_id in args.get("player_ids_to_add") or ():
                await target.group.add_client(await self._client(player_id))
        elif command == "players/cmd/volume_set":
            _role(await self._client(args["player_id"]), "player").set_player_volume(  # type: ignore[union-attr]
                int(args["volume_level"])
            )
        elif command == "players/cmd/group_volume":
            group_role = (await self._client(args["player_id"])).group.group_role("player")
            if group_role is not None:
                group_role.set_group_volume(int(args["volume_level"]))
        elif command == "players/cmd/volume_mute":
            _role(await self._client(args["player_id"]), "player").set_player_mute(  # type: ignore[union-attr]
                bool(args["muted"])
            )
        else:
            raise BackendError(f"unsupported command {command}")

    def _known(self, player_id: str) -> SendspinClient:
        client = self._server.get_client(player_id) if self._server else None
        if client is None:
            raise BackendError(f"speaker {player_id} is not available")
        return client

    async def _client(self, player_id: str) -> SendspinClient:
        """A connected speaker, claimed from another server first if needed.

        Commands must reach the speaker: a start volume sent while it still
        listens to another server would be lost, and it would start loud.
        """
        client = self._known(player_id)
        if client.is_connected:
            self._apply_speaker_buffer(client)
            return client
        assert self._server is not None
        if not self._server.request_client_playback_connection(player_id):
            raise BackendError(f"{client.name} is not reachable")
        logger.info("Claiming %s for playback", client.name)
        try:
            async with asyncio.timeout(CLAIM_TIMEOUT_S):
                while not (client.is_connected and _role(client, "player")):
                    await asyncio.sleep(0.1)
        except TimeoutError:
            raise BackendError(f"{client.name} didn't switch to ToothSpin") from None
        self._apply_speaker_buffer(client)
        return client

    def _legacy_note(self, client: SendspinClient) -> str:
        """A speaker on an older Sendspin version: what that means here, in one line.

        aiosendspin's own warnings about it only show at log level debug (see
        ``watch_sendspin_logs``).
        """
        connection = client.connection
        if not _is_player(client) or connection is None or connection.is_encrypted:
            return ""
        buffer = (
            "assuming a 1000 ms buffer" if self._speaker_buffer_ms is None
            else f"using a {self._speaker_buffer_ms} ms buffer"
        ) if _NO_TIMING_REPORTED in client._noncompliance_logged else "its own buffer"  # noqa: SLF001
        return f" (older Sendspin version: unencrypted, {buffer})"

    def _apply_speaker_buffer(self, client: SendspinClient) -> None:
        """Use the configured buffer on a speaker that doesn't report its own.

        Before any command, so a stream starting on it already uses it. A
        speaker that reports a buffer knows what it needs and keeps it.
        """
        if self._speaker_buffer_ms is None:
            return
        role = _role(client, "player")
        if role is None or _NO_TIMING_REPORTED not in client._noncompliance_logged:  # noqa: SLF001
            return
        if role.min_buffer_ms != self._speaker_buffer_ms:  # type: ignore[attr-defined]
            role.min_buffer_ms = self._speaker_buffer_ms  # type: ignore[attr-defined]
            logger.info("Using a %d ms buffer for %s", self._speaker_buffer_ms, client.name)
    # --- dropouts per speaker ---

    def note_late(self, client_id: str, chunks: int) -> None:
        """aiosendspin dropped audio it couldn't send to this speaker in time."""
        session = self._sessions.get(client_id)
        if session is None:
            return
        session.late_chunks += chunks
        session.late_times += 1
        logger.warning(
            "%s: %d piece(s) of audio arrived too late to play (slow network to it)",
            session.name, chunks,
        )

    def _track_sessions(self) -> None:
        """Start a session per speaker that starts playing, sum it up when it stops."""
        playing = {
            c.client_id: c
            for feed in self._feeds.values()
            for route in feed.routes
            for c in route.group.clients
            if _is_player(c)
        }
        now = time.monotonic()
        for client_id, client in playing.items():
            if client_id not in self._sessions:
                self._sessions[client_id] = _Session(client.name, now)
        for client_id in [c for c in self._sessions if c not in playing]:
            session = self._sessions.pop(client_id)
            client = self._server.get_client(client_id) if self._server else None
            role = _role(client, "player") if client else None
            # Dropped since aiosendspin's last warning, which comes every 30 s.
            pending = getattr(role, "_late_skips_since_log", 0)
            session.late_chunks += pending
            session.late_times += 1 if pending else 0
            minutes = (now - session.started) / 60
            if session.late_chunks:
                logger.warning(
                    "%s played for %.0f min; %d time(s) audio arrived too late to play "
                    "(%d piece(s)). Check its Wi-Fi.",
                    session.name, minutes, session.late_times, session.late_chunks,
                )
            else:
                logger.info("%s played for %.0f min without dropouts", session.name, minutes)

    # --- track info ---

    def _update_metadata(self) -> None:
        """Send each group the track its phone plays; aiosendspin only sends changes."""
        if self._now_playing is None:
            return
        for source_id, feed in self._feeds.items():
            playing = self._now_playing(source_id)
            for route in feed.routes:
                delay_ms = (route.target_delay_us or 0) // 1000
                _set_metadata(route.group, _metadata(playing, delay_ms))

    # --- routing inputs to groups ---

    def _route(self, group: SendspinGroup) -> _Route | None:
        for feed in self._feeds.values():
            for route in feed.routes:
                if route.group is group:
                    return route
        return None

    async def _play(self, client: SendspinClient, media: str) -> None:
        if not media.startswith(SOURCE_PREFIX):
            raise BackendError(f"can only play phone inputs, not {media}")
        source_id = media.removeprefix(SOURCE_PREFIX)
        source = self._server.get_client(source_id) if self._server else None
        source_role = _role(source, "source") if source else None
        if source_role is None:
            raise BackendError("that phone's input isn't connected")
        group = client.group
        current = self._route(group)
        if current is not None:
            if current.source_id == source_id:
                return
            await self._stop(group)
        feed = self._feeds.setdefault(source_id, _Feed())
        feed.routes.append(_Route(group, source_id))
        if feed.task is None or feed.task.done():
            source_role.request_start()  # type: ignore[attr-defined]
        logger.info("Playing %s on %s", source.name, client.name)  # type: ignore[union-attr]

    async def _stop(self, group: SendspinGroup) -> None:
        route = self._route(group)
        if route is None:
            return
        feed = self._feeds[route.source_id]
        feed.routes.remove(route)
        _set_metadata(group, None)
        await group.stop()
        if not feed.routes:
            source = self._server.get_client(route.source_id) if self._server else None
            if source is not None and (role := _role(source, "source")) is not None:
                role.request_stop()  # type: ignore[attr-defined]

    def _on_server_event(self, server: SendspinServer, event: object) -> None:
        if isinstance(event, ClientAddedEvent):
            client = server.get_client(event.client_id)
            if client is not None:
                client.add_event_listener(self._on_client_event)
                logger.info("Found Sendspin client %s%s", client.name, self._legacy_note(client))
        if isinstance(event, ClientAddedEvent | ClientConnectedEvent):
            client = server.get_client(event.client_id)
            if client is not None:
                asyncio.ensure_future(self._trust_speaker(client))

    async def _trust_speaker(self, client: SendspinClient) -> None:
        """Play on speakers that allow servers they aren't paired with.

        Whether that's allowed is the speaker's setting; ToothSpin only plays
        where the user switches a speaker on. Speakers that insist on pairing
        aren't supported yet.
        """
        info = client.info_or_none
        if info is None or not any(r.startswith("player@") for r in info.supported_roles):
            return
        if client.is_paired or not info.unpaired_access.enabled:
            return
        assert self._server is not None and self._store is not None
        if await self._store.trusted_unpaired(client.client_id) is None:
            await self._server.trust_unpaired(client.client_id)
            logger.info("Trusting speaker %s for unpaired playback", client.name)

    def _on_client_event(self, client: SendspinClient, event: object) -> None:
        if isinstance(event, SourceStreamStartedEvent):
            feed = self._feeds.setdefault(client.client_id, _Feed())
            if feed.task is not None:
                feed.task.cancel()
            feed.task = asyncio.create_task(
                self._forward(feed, event.handle, event.audio_format),
                name=f"forward {client.name}",
            )
            feed.task.add_done_callback(_log_failure)
            logger.info("Receiving %s", client.name)

    async def _forward(self, feed: _Feed, handle: SourceStream, fmt: AudioFormat) -> None:
        """Copy an input's audio into the streams of all groups playing it."""
        try:
            async for pcm, timestamp_us in handle:
                for route in list(feed.routes):
                    await self._push(route, pcm, fmt, timestamp_us)
        finally:
            for route in feed.routes:
                route.stream = None
                route.target_delay_us = route.delay_us = None

    async def _push(self, route: _Route, pcm: bytes, fmt: AudioFormat, timestamp_us: int) -> None:
        if route.stream is None or route.stream.is_stopped:
            route.stream = route.group.start_stream()
            route.stream.set_live_source(True)
            route.target_delay_us = route.delay_us = None
        frame = fmt.channels * fmt.bit_depth // 8
        if route.target_delay_us is not None and route.delay_us is not None and len(pcm) > frame:
            pcm = correct_drift(pcm, frame, route.target_delay_us, route.delay_us)
        route.stream.prepare_audio(pcm, fmt)
        try:
            play_us = await route.stream.commit_audio()
        except StreamStoppedError:
            route.stream = None
            return
        route.delay_us = play_us - timestamp_us
        if route.target_delay_us is None:
            route.target_delay_us = route.delay_us
            names = ", ".join(c.name for c in route.group.clients if _is_player(c))
            logger.info(
                "Playing on %s %d ms after ToothSpin received the audio",
                names, route.delay_us // 1000,
            )


def _metadata(playing: NowPlaying | None, delay_ms: int) -> Metadata | None:
    """Sendspin track info from what the phone reports.

    The speakers play ``delay_ms`` behind the phone, so the position they
    show is moved back by that much.
    """
    if playing is None or not (playing.title or playing.artist):
        return None
    metadata = Metadata(title=playing.title, artist=playing.artist, album=playing.album)
    if playing.position_ms is None:
        return metadata
    return replace(
        metadata,
        track_progress=max(0, playing.position_ms - delay_ms),
        # 0: unknown length.
        track_duration=playing.duration_ms or 0,
        playback_speed=1000 if playing.status == "playing" else 0,
    )


def _set_metadata(group: SendspinGroup, metadata: Metadata | None) -> None:
    role = group.group_role("metadata")
    if role is not None:
        role.set_metadata(metadata)  # type: ignore[attr-defined]


def _log_failure(task: asyncio.Task[None]) -> None:
    if not task.cancelled() and task.exception() is not None:
        logger.error("%s failed", task.get_name(), exc_info=task.exception())


def correct_drift(pcm: bytes, frame: int, target_us: int, delay_us: int) -> bytes:
    """Drop or repeat one frame when the phone-to-speaker delay drifts.

    The stream's timeline advances by the samples it gets, the capture
    timestamps by the phone's real time. A phone clocked slightly fast hands
    over more samples than the speakers play, so the delay grows; one frame
    (21 us at 48 kHz) per 20 ms chunk is inaudible and outpaces any real drift.
    """
    if delay_us > target_us + DRIFT_TOLERANCE_US:
        return pcm[:-frame]
    if delay_us < target_us - DRIFT_TOLERANCE_US:
        return pcm + pcm[-frame:]
    return pcm


def _is_player(client: SendspinClient) -> bool:
    return has_role_family("player", client.negotiated_role_ids)


def _role(client: SendspinClient, family: str) -> object | None:
    roles = client.roles_by_family(family)
    return roles[0] if roles else None


# aiosendspin warns about every speaker on an older Sendspin version, several
# lines each, on every start; ToothSpin says it in one line instead.
_LEGACY_WARNINGS = ("non-compliant client:", "Accepting unencrypted legacy connection")
# aiosendspin's warning (at most every 30 s per speaker) that it dropped audio
# it couldn't send to a speaker in time; its arguments are (type, role,
# chunks, ...). ToothSpin counts them per speaker instead.
_LATE_WARNING = "Late binary type="


class _SendspinLogs(logging.Filter):
    """Turns aiosendspin's verbose warnings into ToothSpin's own short ones."""

    def __init__(self, on_late: Callable[[str, int], None] | None = None) -> None:
        super().__init__()
        self._on_late = on_late

    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno != logging.WARNING or not record.name.startswith("aiosendspin.server."):
            return True
        msg = str(record.msg)
        if msg.startswith(_LATE_WARNING) and isinstance(record.args, tuple) and len(record.args) > 2:
            if record.args[1] != "player":
                return True
            if self._on_late is not None:
                # The connection's logger is named after the speaker's client id.
                self._on_late(record.name.rsplit(".", 1)[-1], int(record.args[2]))
        elif not msg.startswith(_LEGACY_WARNINGS):
            return True
        record.levelno, record.levelname = logging.DEBUG, "DEBUG"
        return logging.getLogger().isEnabledFor(logging.DEBUG)


def watch_sendspin_logs(on_late: Callable[[str, int], None] | None = None) -> None:
    """Show aiosendspin's warnings about older speakers and late audio only at
    log level debug, and hand the late audio to ``on_late`` (client id, chunks)."""
    for handler in logging.getLogger().handlers:
        handler.addFilter(_SendspinLogs(on_late))
