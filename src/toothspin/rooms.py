"""Fixed speaker groups ("rooms") for the standalone server.

A room is a few speakers that always play together and show as one speaker,
e.g. a left and a right one as "Living room". Only the standalone server has
them: Music Assistant has its own speaker groups.
"""

from __future__ import annotations

import json
import secrets
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Room:
    id: str
    name: str
    members: tuple[str, ...]
    """The speakers' client ids; the first leads the room's group."""


class RoomStore:
    """The rooms, kept in a JSON file."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._rooms: dict[str, Room] = {}
        if path.exists():
            for raw in json.loads(path.read_text()):
                room = Room(raw["id"], raw["name"], tuple(raw["members"]))
                self._rooms[room.id] = room

    def __iter__(self):  # noqa: ANN204
        return iter(sorted(self._rooms.values(), key=lambda r: r.name.lower()))

    def get(self, room_id: str) -> Room | None:
        return self._rooms.get(room_id)

    def of(self, client_id: str) -> Room | None:
        """The room a speaker belongs to."""
        return next((r for r in self._rooms.values() if client_id in r.members), None)

    def put(self, room_id: str | None, name: str, members: tuple[str, ...]) -> Room:
        """Create a room (no id) or change one; a speaker is in one room at most."""
        if len(members) < 2 or len(set(members)) != len(members):
            raise ValueError("A group needs at least two different speakers")
        for member in members:
            other = self.of(member)
            if other is not None and other.id != room_id:
                raise ValueError(f"A speaker is already in {other.name}")
        if room_id is not None and room_id not in self._rooms:
            raise KeyError(room_id)
        room = Room(room_id or f"room-{secrets.token_hex(4)}", name, members)
        self._rooms[room.id] = room
        self._save()
        return room

    def delete(self, room_id: str) -> Room:
        room = self._rooms.pop(room_id)
        self._save()
        return room

    def _save(self) -> None:
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps([asdict(r) for r in self._rooms.values()], indent=2))
        tmp.replace(self._path)
