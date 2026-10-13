"""Speaker toggles: which Music Assistant players a phone's input plays on.

Toggling several speakers for one phone groups them on the fly (MA sync
grouping via ``players/cmd/set_members``); toggling one off takes it out of
the group. Music Assistant is the source of truth: the current selection is
read back from its player state, never stored here.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from .ma import MusicAssistant, MusicAssistantError

SOURCE_URI = "sendspin_source://audio_source/{client_id}"
# MA applies commands asynchronously; e.g. playing on a speaker that still
# counts as synced to a group plays on the group leader instead. So after
# each command, wait (up to this long) until MA's state reflects it.
SETTLE_TIMEOUT_S = 5.0
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


def speakers(players: list[dict[str, Any]]) -> list[Speaker]:
    """Available output players, by name."""
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
        raise MusicAssistantError(f"speaker {player_id} is not available")
    selected = speaker.playing_uri == uri

    if not on:
        return _release(all_speakers, speaker) if selected else []
    if selected:
        return []

    leader = _leader(all_speakers, uri)
    if leader is not None and player_id not in leader.can_group_with:
        raise MusicAssistantError(f"{speaker.name} can't play in sync with {leader.name}")
    # A speaker playing another phone's input is taken over.
    commands = _release(all_speakers, speaker)
    if leader is None:
        commands.append(("player_queues/play_media", {"queue_id": player_id, "media": uri}))
    else:
        commands.append(("players/cmd/set_members",
                         {"target_player": leader.player_id, "player_ids_to_add": [player_id]}))
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


async def toggle(ma: MusicAssistant, uri: str, player_id: str, on: bool) -> None:
    await ma.refresh()
    for command, args in plan(ma.players, uri, player_id, on):
        await ma.call(command, **args)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + SETTLE_TIMEOUT_S
        while True:
            await ma.refresh()
            if _applied(ma.players, command, args) or loop.time() > deadline:
                break
            await asyncio.sleep(SETTLE_POLL_S)
