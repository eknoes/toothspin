"""The speaker backend: who plays the phones' inputs on which speakers.

ToothSpin either uses Music Assistant (``ma.MusicAssistant``) or runs its own
Sendspin server (``server.ToothSpinServer``). Both offer the same small slice
of Music Assistant's player API, so speaker toggles, grouping, volume and the
phone volume sync work the same on either.
"""

from __future__ import annotations

from typing import Any, Protocol

# The commands both backends understand, with Music Assistant's names and
# arguments:
#   player_queues/play_media   queue_id, media (an input's source URI)
#   players/cmd/stop           player_id
#   players/cmd/set_members    target_player, player_ids_to_add/_remove
#   players/cmd/volume_set     player_id, volume_level (0-100)
#   players/cmd/group_volume   player_id (the group leader), volume_level
#   players/cmd/volume_mute    player_id, muted


class BackendError(Exception):
    """A speaker command failed."""


class PlayerBackend(Protocol):
    players: list[dict[str, Any]]
    """Players in Music Assistant's format (player_id, name, type, available,
    playback_state, active_source, synced_to, group_members, can_group_with,
    volume_level, group_volume, volume_muted, volume_control, mute_control)."""

    @property
    def connected(self) -> bool: ...

    async def run(self) -> None:
        """Keep ``players`` current until cancelled."""

    async def refresh(self) -> None:
        """Update ``players`` now."""

    async def call(self, command: str, **args: Any) -> Any: ...
