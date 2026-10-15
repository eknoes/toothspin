"""Speaker toggles: which Music Assistant players a phone's input plays on.

Toggling several speakers for one phone groups them on the fly (MA sync
grouping via ``players/cmd/set_members``); toggling one off takes it out of
the group. Moving a phone to one speaker switches rooms in one go. Music
Assistant is the source of truth: the current selection is
read back from its player state, never stored here.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any

from .backend import BackendError, PlayerBackend

SOURCE_URI = "sendspin_source://audio_source/{client_id}"
# MA applies commands asynchronously; e.g. playing on a speaker that still
# counts as synced to a group plays on the group leader instead. So after
# each command, wait (up to this long) until MA's state reflects it.
SETTLE_TIMEOUT_S = 5.0
# A speaker just taken out of a group (or stopped) is still ending its old
# stream (Music Assistant waits for it to drain its buffer, about a second).
# Started or grouped again right away, a Sendspin speaker can stay silent.
RELEASE_GAP_S = 1.5
# When each speaker was last released, across requests: a quick second click
# may start one the click before released.
_released_at: dict[str, float] = {}
SETTLE_POLL_S = 0.25


def source_uri(client_id: str) -> str:
    return SOURCE_URI.format(client_id=client_id)


@dataclass(frozen=True, slots=True)
class Speaker:
    player_id: str
    name: str
    can_group_with: frozenset[str]
    playing_uri: str | None
    """The phone input (audio source URI) this speaker is playing, if any."""
    synced_to: str | None
    """Group leader this speaker follows, if it isn't the leader itself."""
    members: tuple[str, ...]
    """Group members incl. itself, when this speaker leads a group."""
    volume: int | None
    group_volume: int | None
    """Volume of the group this speaker leads (MA averages its members)."""
    muted: bool
    has_volume: bool
    has_mute: bool
    """Whether the speaker can mute itself; otherwise mute is emulated."""


def speakers(
    players: list[dict[str, Any]], emulated_mutes: dict[str, int] | None = None
) -> list[Speaker]:
    """Available output players, by name."""
    emulated_mutes = emulated_mutes or {}
    result = []
    for p in players:
        if not p.get("available") or p.get("type") not in ("player", "group"):
            continue
        active = p.get("active_source") or ""
        playing = p.get("playback_state") not in (None, "idle") and active.startswith(
            "sendspin_source://"
        )
        result.append(
            Speaker(
                player_id=p["player_id"],
                name=p.get("name") or p["player_id"],
                can_group_with=frozenset(p.get("can_group_with") or ()),
                playing_uri=active if playing else None,
                synced_to=p.get("synced_to"),
                members=tuple(p.get("group_members") or ()),
                volume=p.get("volume_level"),
                group_volume=p.get("group_volume"),
                muted=bool(p.get("volume_muted")) or p["player_id"] in emulated_mutes,
                has_volume=p.get("volume_control") not in (None, "none"),
                has_mute=p.get("mute_control") not in (None, "none"),
            )
        )
    return sorted(result, key=lambda s: s.name.lower())


Command = tuple[str, dict[str, Any]]


def _leader(all_speakers: dict[str, Speaker], uri: str) -> Speaker | None:
    for speaker in all_speakers.values():
        if speaker.playing_uri == uri and speaker.synced_to is None:
            return speaker
    return None


def _followers(leader: Speaker) -> list[str]:
    return [m for m in leader.members if m != leader.player_id]


def _release(all_speakers: dict[str, Speaker], speaker: Speaker) -> list[Command]:
    """Take a speaker out of whatever input it plays, keeping the rest of its group."""
    uri = speaker.playing_uri
    if uri is None:
        return []
    if speaker.synced_to is not None:
        return [("players/cmd/set_members",
                 {"target_player": speaker.synced_to, "player_ids_to_remove": [speaker.player_id]})]
    rest = _followers(speaker)
    if not rest:
        return [("players/cmd/stop", {"player_id": speaker.player_id})]
    # The leader goes: hand the input to the next member, then regroup the others.
    commands: list[Command] = [
        ("players/cmd/set_members",
         {"target_player": speaker.player_id, "player_ids_to_remove": rest}),
        ("player_queues/play_media", {"queue_id": rest[0], "media": uri}),
    ]
    if rest[1:]:
        commands.append(("players/cmd/set_members",
                         {"target_player": rest[0], "player_ids_to_add": rest[1:]}))
    commands.append(("players/cmd/stop", {"player_id": speaker.player_id}))
    return commands


def plan(players: list[dict[str, Any]], uri: str, player_id: str, on: bool) -> list[Command]:
    """MA commands that toggle ``player_id`` on/off for the input ``uri``."""
    all_speakers = {s.player_id: s for s in speakers(players)}
    speaker = all_speakers.get(player_id)
    if speaker is None:
        raise BackendError(f"speaker {player_id} is not available")
    selected = speaker.playing_uri == uri

    if not on:
        return _release(all_speakers, speaker) if selected else []
    if selected:
        return []

    leader = _leader(all_speakers, uri)
    if leader is not None and player_id not in leader.can_group_with:
        raise BackendError(f"{speaker.name} can't play in sync with {leader.name}")
    # A speaker playing another phone's input is taken over.
    commands = _release(all_speakers, speaker)
    if leader is None:
        commands.append(("player_queues/play_media", {"queue_id": player_id, "media": uri}))
    else:
        commands.append(("players/cmd/set_members",
                         {"target_player": leader.player_id, "player_ids_to_add": [player_id]}))
    return commands


def plan_move(players: list[dict[str, Any]], uri: str, player_id: str) -> list[Command]:
    """MA commands that make ``player_id`` the only speaker playing ``uri``."""
    all_speakers = {s.player_id: s for s in speakers(players)}
    speaker = all_speakers.get(player_id)
    if speaker is None:
        raise BackendError(f"speaker {player_id} is not available")
    leader = _leader(all_speakers, uri)
    if leader is None:
        return plan(players, uri, player_id, True)
    followers = _followers(leader)
    if leader.player_id == player_id:
        return [("players/cmd/set_members",
                 {"target_player": player_id, "player_ids_to_remove": followers})] if followers else []
    # Ungroup the old speakers (including this one, if it was one of them),
    # start this one, then stop the old leader.
    commands: list[Command] = []
    if followers:
        commands.append(("players/cmd/set_members",
                         {"target_player": leader.player_id, "player_ids_to_remove": followers}))
    if player_id not in followers:
        # A speaker playing another phone's input is taken over.
        commands += _release(all_speakers, speaker)
    commands.append(("player_queues/play_media", {"queue_id": player_id, "media": uri}))
    commands.append(("players/cmd/stop", {"player_id": leader.player_id}))
    return commands


def _applied(players: list[dict[str, Any]], command: str, args: dict[str, Any]) -> bool:
    """Whether MA's player state shows ``command`` took effect."""
    by_id = {s.player_id: s for s in speakers(players)}
    if command == "player_queues/play_media":
        speaker = by_id.get(args["queue_id"])
        return speaker is not None and speaker.playing_uri == args["media"]
    if command == "players/cmd/stop":
        speaker = by_id.get(args["player_id"])
        return speaker is None or speaker.playing_uri is None
    if command == "players/cmd/set_members":
        target = args["target_player"]
        added = all(
            (s := by_id.get(p)) is None or s.synced_to == target
            for p in args.get("player_ids_to_add") or ()
        )
        removed = all(
            (s := by_id.get(p)) is None or s.synced_to != target
            for p in args.get("player_ids_to_remove") or ()
        )
        return added and removed
    return True


def quiet_start(
    players: list[dict[str, Any]], uri: str, player_id: str, start_volume: int
) -> list[Command]:
    """Turn a speaker left loud down to the start volume before ``uri`` starts on it."""
    speaker = next((s for s in speakers(players) if s.player_id == player_id), None)
    # An unknown volume (e.g. a speaker still with another server) may be loud.
    # A speaker without volume control (e.g. one turned up and down by an
    # amplifier after it) is left alone.
    if speaker is None or speaker.playing_uri == uri or not speaker.has_volume or (
        speaker.volume is not None and speaker.volume <= start_volume
    ):
        return []
    return [("players/cmd/volume_set", {"player_id": player_id, "volume_level": start_volume})]


class GroupingRefused(BackendError):
    """Music Assistant accepted a grouping command but didn't group.

    Seen when a stale player record (e.g. of a former Squeezelite player)
    shares the speaker's ID and hides its Sendspin output; see the FAQ.
    """


async def toggle(
    backend: PlayerBackend, uri: str, player_id: str, on: bool, start_volume: int = 100
) -> None:
    await backend.refresh()
    commands = plan(backend.players, uri, player_id, on)
    if on and commands:
        commands = quiet_start(backend.players, uri, player_id, start_volume) + commands
    await _run(backend, commands)


async def move(backend: PlayerBackend, uri: str, player_id: str, start_volume: int = 100) -> None:
    await backend.refresh()
    commands = plan_move(backend.players, uri, player_id)
    if commands:
        commands = quiet_start(backend.players, uri, player_id, start_volume) + commands
    await _run(backend, commands)


def _released(command: str, args: dict[str, Any]) -> set[str]:
    """Speakers a command takes out of what they were playing."""
    if command == "players/cmd/set_members":
        return set(args.get("player_ids_to_remove") or ())
    if command == "players/cmd/stop":
        return {args["player_id"]}
    return set()


def _started(command: str, args: dict[str, Any]) -> set[str]:
    """Speakers a command starts or adds to a group."""
    if command == "player_queues/play_media":
        return {args["queue_id"]}
    if command == "players/cmd/set_members":
        return set(args.get("player_ids_to_add") or ())
    return set()


async def _run(backend: PlayerBackend, commands: list[Command]) -> None:
    loop = asyncio.get_running_loop()
    for command, args in commands:
        if waits := [_released_at[p] + RELEASE_GAP_S - time.monotonic()
                     for p in _started(command, args) if p in _released_at]:
            await asyncio.sleep(max(0.0, *waits))
        await backend.call(command, **args)
        for player_id in _released(command, args):
            _released_at[player_id] = time.monotonic()
        deadline = loop.time() + SETTLE_TIMEOUT_S
        while True:
            await backend.refresh()
            if _applied(backend.players, command, args):
                break
            if loop.time() > deadline:
                if command == "players/cmd/set_members" and args.get("player_ids_to_add"):
                    names = {s.player_id: s.name for s in speakers(backend.players)}
                    added = ", ".join(names.get(p, p) for p in args["player_ids_to_add"])
                    target = names.get(args["target_player"], args["target_player"])
                    raise GroupingRefused(
                        f"Music Assistant didn't group {added} with {target}"
                    )
                break
            await asyncio.sleep(SETTLE_POLL_S)


class Volumes:
    """Volume and mute; mute is emulated (volume 0, then restore) where unsupported."""

    def __init__(self, backend: PlayerBackend) -> None:
        self._backend = backend
        # player_id -> volume to restore, for speakers muted by emulation.
        self.emulated_mutes: dict[str, int] = {}

    def _speaker(self, player_id: str) -> Speaker:
        for speaker in speakers(self._backend.players, self.emulated_mutes):
            if speaker.player_id == player_id:
                return speaker
        raise BackendError(f"speaker {player_id} is not available")

    async def set_volume(self, player_id: str, volume: int) -> None:
        volume = max(0, min(100, volume))
        self.emulated_mutes.pop(player_id, None)
        await self._backend.call("players/cmd/volume_set", player_id=player_id, volume_level=volume)
        await self._backend.refresh()

    async def set_muted(self, player_id: str, muted: bool) -> None:
        speaker = self._speaker(player_id)
        if speaker.has_mute:
            await self._backend.call("players/cmd/volume_mute", player_id=player_id, muted=muted)
        elif muted and player_id not in self.emulated_mutes:
            self.emulated_mutes[player_id] = speaker.volume or 0
            await self._backend.call("players/cmd/volume_set", player_id=player_id, volume_level=0)
        elif not muted and player_id in self.emulated_mutes:
            restore = self.emulated_mutes.pop(player_id)
            await self._backend.call("players/cmd/volume_set", player_id=player_id, volume_level=restore)
        await self._backend.refresh()
