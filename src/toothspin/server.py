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
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, Any

from aiosendspin.models.types import GoodbyeReason, has_role_family
from aiosendspin.noise import FileServerPairingStore
from aiosendspin.noise.keys import generate_psk, psk_id_for
from aiosendspin.noise.trust_store import PairingPsk, StagedPairingPsk
from aiosendspin.server import (
    ClientAddedEvent,
    ClientConnectedEvent,
    ClientDisconnectedEvent,
    SendspinServer,
    SourceStreamStartedEvent,
)
from aiosendspin.server.push_stream import StreamStoppedError
from aiosendspin.server.roles.metadata.state import Metadata
from PIL import Image, UnidentifiedImageError

from .backend import BackendError
from .rooms import Room, RoomStore
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
# Right after boot, mDNS can fail until the network is up; aiosendspin then
# serves on without it, so speakers never find the server: start again after
# this long, doubling up to the maximum.
START_RETRY_S = 2.0
START_RETRY_MAX_S = 60.0
# How often to look for new track info from the phones.
METADATA_S = 1.0
# How aiosendspin notes a speaker that doesn't report its timing
# (min_buffer_ms and others), at the end of a reason like "client/state
# omitted ...": it then assumes a buffer of 1000 ms.
_NO_TIMING_REPORTED = "omitted required player timing fields"
# Keep the delay from phone to speakers within this of where it started:
# phone and speakers run on slightly different clocks.
DRIFT_TOLERANCE_US = 20_000
# An input quiet for this long has stopped, e.g. the phone paused. Its
# speakers' stream is then ended, as speakers left on an empty stream don't
# play when audio comes back on it; the phone's next audio starts a new one
# on the same speakers.
IDLE_STREAM_S = 2.0
# A speaker that leaves for these reasons was told to (by its user, or by
# another server taking it over); it doesn't play the phone again on return.
_DELIBERATE_GOODBYES = {GoodbyeReason.ANOTHER_SERVER, GoodbyeReason.USER_REQUEST}


@dataclass(eq=False, slots=True)
class _Route:
    """A group playing an input, with its stream and drift correction state."""

    group: SendspinGroup
    source_id: str
    stream: PushStream | None = None
    target_delay_us: int | None = None
    """Phone-to-speaker delay when the stream started; drift is corrected towards it."""
    delay_us: int | None = None
    lost: set[str] = field(default_factory=set)
    cover: str | None = None
    """Image handle of the cover the group shows."""
    """Speakers that dropped off while playing it, by client id: they play it again on return."""


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
    last_audio: float = 0.0
    """When the input's audio last arrived (monotonic)."""


class ToothSpinServer:
    def __init__(
        self,
        data_dir: Path,
        name: str,
        port: int = 8927,
        speaker_buffer_ms: int | None = None,
        now_playing: Callable[[str], NowPlaying | None] | None = None,
        cover: Callable[[str], tuple[str, bytes] | None] | None = None,
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
        # The phone's cover as (image handle, JPEG), by its source's client id.
        self._cover = cover
        # Speakers playing a phone now, by client id.
        self._sessions: dict[str, _Session] = {}
        self._server: SendspinServer | None = None
        self._store: FileServerPairingStore | None = None
        self._feeds: dict[str, _Feed] = {}
        self._started = asyncio.Event()
        self._rooms = RoomStore(self._data_dir / "rooms.json")

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
                if self._server._zc is None:  # noqa: SLF001
                    await self._server.stop_server()
                    raise OSError(errno.ENETDOWN, "mDNS unavailable")
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
                await self._update_covers()
                self._track_sessions()
                self._end_idle_streams()
                try:
                    await self._keep_rooms()
                except Exception:
                    logger.exception("Couldn't group speaker groups again")
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
    #
    # A room's speakers show as one player of type "group" with the room's id;
    # commands to it go to all of them.

    @property
    def players(self) -> list[dict[str, Any]]:
        if self._server is None:
            return []
        players = []
        rooms_seen = set()
        for client in self._server.clients:
            if not _is_player(client):
                continue
            room = self._rooms.of(client.client_id)
            if room is None:
                players.append(self._player(client))
            elif room.id not in rooms_seen:
                rooms_seen.add(room.id)
                players.append(self._room_player(room))
        return players

    def _player(self, client: SendspinClient) -> dict[str, Any]:
        role = _role(client, "player")
        return {
            **self._grouping(client.client_id, client.group),
            "name": client.name,
            "type": "player",
            # Speakers connected to another server can be claimed for playback.
            "available": client.is_connected or client.info_or_none is not None,
            "volume_level": getattr(role, "volume", None),
            "volume_muted": bool(getattr(role, "muted", False)),
            "volume_control": "internal" if role else "none",
            "mute_control": "internal" if role else "none",
        }

    def _room_player(self, room: Room) -> dict[str, Any]:
        clients = self._room_clients(room)
        anchor = self._anchor(room)
        assert anchor is not None
        roles = [r for c in clients if (r := _role(c, "player")) is not None]
        volumes = [v for r in roles if (v := getattr(r, "volume", None)) is not None]
        return {
            **self._grouping(room.id, anchor.group),
            "name": room.name,
            "type": "group",
            "available": any(c.is_connected or c.info_or_none is not None for c in clients),
            "volume_level": round(sum(volumes) / len(volumes)) if volumes else None,
            "volume_muted": bool(roles) and all(getattr(r, "muted", False) for r in roles),
            "volume_control": "internal" if roles else "none",
            "mute_control": "internal" if roles else "none",
        }

    def _grouping(self, player_id: str, group: SendspinGroup) -> dict[str, Any]:
        """What a player plays and whom it's grouped with, as Music Assistant has it."""
        members = []
        for c in group.clients:
            if _is_player(c) and (visible := self._player_id(c)) not in members:
                members.append(visible)
        leader = members[0] if members else player_id
        route = self._route(group)
        group_role = group.group_role("player")
        return {
            "player_id": player_id,
            "provider": "toothspin",
            "can_group_with": sorted(
                {self._player_id(c) for c in self._server.clients if _is_player(c)}  # type: ignore[union-attr]
                - {player_id}
            ),
            "playback_state": "playing" if route else "idle",
            "active_source": SOURCE_PREFIX + route.source_id if route else None,
            "synced_to": leader if leader != player_id else None,
            "group_members": members if leader == player_id and len(members) > 1 else [],
            "group_volume": group_role.get_group_volume() if group_role else None,
        }

    def _player_id(self, client: SendspinClient) -> str:
        """The player a speaker shows as: its room, or itself."""
        room = self._rooms.of(client.client_id)
        return room.id if room else client.client_id

    async def call(self, command: str, **args: Any) -> Any:
        if command == "player_queues/play_media":
            clients = await self._connected(args["queue_id"])
            leader = self._lead(args["queue_id"])
            await self._play(leader, args["media"])
            for client in clients:
                await leader.group.add_client(client)
        elif command == "players/cmd/stop":
            await self._stop(self._lead(args["player_id"]).group)
        elif command == "players/cmd/set_members":
            await self._connected(args["target_player"])
            target = self._lead(args["target_player"])
            for player_id in args.get("player_ids_to_remove") or ():
                await self._ungroup(player_id)
            for player_id in args.get("player_ids_to_add") or ():
                for client in await self._connected(player_id):
                    await target.group.add_client(client)
        elif command == "players/cmd/volume_set":
            for client in await self._connected(args["player_id"]):
                _role(client, "player").set_player_volume(int(args["volume_level"]))  # type: ignore[union-attr]
        elif command == "players/cmd/group_volume":
            await self._connected(args["player_id"])
            group_role = self._lead(args["player_id"]).group.group_role("player")
            if group_role is not None:
                group_role.set_group_volume(int(args["volume_level"]))
        elif command == "players/cmd/volume_mute":
            for client in await self._connected(args["player_id"]):
                _role(client, "player").set_player_mute(bool(args["muted"]))  # type: ignore[union-attr]
        else:
            raise BackendError(f"unsupported command {command}")

    def _known(self, player_id: str) -> SendspinClient:
        client = self._server.get_client(player_id) if self._server else None
        if client is None:
            raise BackendError(f"speaker {player_id} is not available")
        return client

    def _lead(self, player_id: str) -> SendspinClient:
        """The speaker whose group a player's commands go to."""
        room = self._rooms.get(player_id)
        if room is None:
            return self._known(player_id)
        anchor = self._anchor(room)
        if anchor is None:
            raise BackendError(f"{room.name}'s speakers are not available")
        return anchor

    async def _connected(self, player_id: str) -> list[SendspinClient]:
        """The speakers a player stands for, connected (see ``_client``).

        A room plays on those of its speakers that can be reached.
        """
        room = self._rooms.get(player_id)
        if room is None:
            return [await self._client(player_id)]
        clients = []
        for member in self._room_clients(room):
            try:
                clients.append(await self._client(member.client_id))
            except BackendError as err:
                logger.warning("%s plays without a speaker: %s", room.name, err)
        if not clients:
            raise BackendError(f"{room.name}'s speakers are not reachable")
        return clients

    async def _ungroup(self, player_id: str) -> None:
        """Take a player out of its group; a room's speakers stay together."""
        room = self._rooms.get(player_id)
        if room is None:
            await self._known(player_id).ungroup()
            return
        clients = [c for c in self._room_clients(room) if c.is_connected]
        if not clients:
            return
        await clients[0].ungroup()
        for client in clients[1:]:
            await clients[0].group.add_client(client)

    # --- rooms ---

    def _room_clients(self, room: Room) -> list[SendspinClient]:
        assert self._server is not None
        return [c for m in room.members if (c := self._server.get_client(m)) is not None]

    def _anchor(self, room: Room) -> SendspinClient | None:
        """The room's speaker whose group is the room's: the one most of it is in."""
        clients = self._room_clients(room)
        connected = [c for c in clients if c.is_connected]
        if not connected:
            return clients[0] if clients else None
        return max(
            connected,
            key=lambda c: (
                self._route(c.group) is not None, sum(m in c.group.clients for m in connected)
            ),
        )

    async def _keep_rooms(self) -> None:
        """Group each room's speakers again that came back on their own."""
        for room in self._rooms:
            anchor = self._anchor(room)
            if anchor is None or not anchor.is_connected:
                continue
            for client in self._room_clients(room):
                if client.is_connected and client not in anchor.group.clients:
                    logger.info("Grouping %s with %s again", client.name, room.name)
                    await anchor.group.add_client(client)

    def rooms(self) -> dict[str, Any]:
        """The rooms and the speakers they can have, for the web UI."""
        speakers = {
            c.client_id: c.name
            for c in (self._server.clients if self._server else ())
            if _is_player(c)
        }
        return {
            "list": [
                {
                    "id": room.id,
                    "name": room.name,
                    "members": [
                        {"id": m, "name": speakers.get(m), "found": m in speakers}
                        for m in room.members
                    ],
                }
                for room in self._rooms
            ],
            "speakers": [
                {"id": i, "name": n, "room": r.id if (r := self._rooms.of(i)) else None}
                for i, n in sorted(speakers.items(), key=lambda kv: kv[1].lower())
            ],
        }

    async def save_room(self, room_id: str | None, name: str, members: list[str]) -> None:
        """Create or change a room. A speaker that leaves it stops playing with it."""
        old = self._rooms.get(room_id) if room_id else None
        try:
            room = self._rooms.put(room_id, name, tuple(members))
        except ValueError as err:
            raise BackendError(str(err)) from None
        except KeyError:
            raise BackendError("That group no longer exists") from None
        logger.info("Speaker group %s: %s", room.name, ", ".join(
            c.name for c in self._room_clients(room)))
        for member in old.members if old else ():
            client = self._server.get_client(member) if self._server else None
            if member not in room.members and client is not None and client.is_connected:
                await client.ungroup()
        await self._keep_rooms()

    async def delete_room(self, room_id: str) -> None:
        """Remove a room; its speakers stay as they are, now each on its own."""
        try:
            room = self._rooms.delete(room_id)
        except KeyError:
            raise BackendError("That group no longer exists") from None
        logger.info("Removed speaker group %s", room.name)

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
        ) if _reports_no_timing(client) else "its own buffer"
        return f" (older Sendspin version: unencrypted, {buffer})"

    def _apply_speaker_buffer(self, client: SendspinClient) -> None:
        """Use the configured buffer on a speaker that doesn't report its own.

        Before any command, so a stream starting on it already uses it. A
        speaker that reports a buffer knows what it needs and keeps it.
        """
        if self._speaker_buffer_ms is None:
            return
        role = _role(client, "player")
        if role is None or not _reports_no_timing(client):
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

    def _end_idle_streams(self) -> None:
        now = time.monotonic()
        for source_id, feed in self._feeds.items():
            if now - feed.last_audio < IDLE_STREAM_S:
                continue
            for route in feed.routes:
                if route.stream is not None:
                    source = self._server.get_client(source_id) if self._server else None
                    names = ", ".join(c.name for c in route.group.clients if _is_player(c))
                    logger.info(
                        "%s stopped playing; %s wait until it plays again",
                        source.name if source else "The phone", names,
                    )
                    route.group.stop_stream()
                    route.stream = None

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

    async def _update_covers(self) -> None:
        """Send each group its phone's cover when it changes."""
        if self._cover is None:
            return
        for source_id, feed in self._feeds.items():
            cover = self._cover(source_id)
            handle = cover[0] if cover else None
            for route in feed.routes:
                if route.cover == handle:
                    continue
                route.cover = handle
                try:
                    image = Image.open(BytesIO(cover[1])) if cover else None
                except UnidentifiedImageError:
                    logger.warning("The phone's cover isn't an image")
                    continue
                await _set_cover(route.group, image)

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
        if route.cover is not None:
            await _set_cover(group, None)
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
                self._rejoin(client)
        if isinstance(event, ClientDisconnectedEvent):
            client = server.get_client(event.client_id)
            route = self._route(client.group) if client is not None else None
            if route is not None and event.goodbye_reason not in _DELIBERATE_GOODBYES:
                route.lost.add(event.client_id)

    def _rejoin(self, client: SendspinClient) -> None:
        """Play a returning speaker's phone again, where it left off.

        A speaker back within seconds is still in its group; one that was
        gone longer (or rebooted) comes back in a group of its own, and
        without this would stay silent while the phone plays on.
        """
        for feed in self._feeds.values():
            for route in feed.routes:
                if client.client_id not in route.lost:
                    continue
                route.lost.discard(client.client_id)
                if client.group is route.group:
                    return
                if any(_is_player(c) and c.is_connected for c in route.group.clients):
                    logger.info("%s is back, rejoining its group", client.name)
                    task = asyncio.ensure_future(route.group.add_client(client))
                    task.add_done_callback(_log_failure)
                    return
                logger.info("%s is back, playing again", client.name)
                route.group = client.group
                route.stream = None
                route.target_delay_us = route.delay_us = None
                route.cover = None
                return

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
                feed.last_audio = time.monotonic()
                for route in list(feed.routes):
                    await self._push(route, pcm, fmt, timestamp_us)
        finally:
            for route in feed.routes:
                route.stream = None
                route.target_delay_us = route.delay_us = None

    async def _push(self, route: _Route, pcm: bytes, fmt: AudioFormat, timestamp_us: int) -> None:
        if not any(_is_player(c) for c in route.group.clients):
            # Its speakers dropped off; they pick the stream up on return.
            return
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


async def _set_cover(group: SendspinGroup, image: Image.Image | None) -> None:
    role = group.group_role("artwork")
    if role is not None:
        await role.set_album_artwork(image)  # type: ignore[attr-defined]


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


def _reports_no_timing(client: SendspinClient) -> bool:
    return any(
        reason.endswith(_NO_TIMING_REPORTED)
        for reason in client._noncompliance_logged  # noqa: SLF001
    )


def _is_player(client: SendspinClient) -> bool:
    return has_role_family("player", client.negotiated_role_ids)


def _role(client: SendspinClient, family: str) -> object | None:
    roles = client.roles_by_family(family)
    return roles[0] if roles else None


# aiosendspin warns about every speaker on an older Sendspin version, several
# lines each ("non-compliant client Kitchen (...): ..."), on every start;
# ToothSpin says it in one line instead.
_LEGACY_WARNING = "non-compliant client"
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
        elif not record.getMessage().startswith(_LEGACY_WARNING):
            return True
        record.levelno, record.levelname = logging.DEBUG, "DEBUG"
        return logging.getLogger().isEnabledFor(logging.DEBUG)


def watch_sendspin_logs(on_late: Callable[[str, int], None] | None = None) -> None:
    """Show aiosendspin's warnings about older speakers and late audio only at
    log level debug, and hand the late audio to ``on_late`` (client id, chunks)."""
    for handler in logging.getLogger().handlers:
        handler.addFilter(_SendspinLogs(on_late))
