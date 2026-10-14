"""Phone volume <-> speaker volume.

While a phone streams to a speaker (or group), its volume buttons set that
speaker's volume, and volume changes made elsewhere (web UI, Music
Assistant) are sent to the phone. When a phone starts streaming to a
speaker, the speaker's current volume wins, capped at the start volume: it's
sent to the phone rather than taking over whatever volume the phone happened
to have, and a speaker left loud doesn't start loud.

Phones report absolute volume as 0-127 (AVRCP); speakers use 0-100. The
captured audio itself stays at full scale (PipeWire's Bluetooth hardware
volume is off), so volume is only ever applied once, at the speaker.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from dataclasses import dataclass

from . import speakers
from .bluez import BluetoothManager, Transport
from .backend import BackendError, PlayerBackend
from .receivers import Receivers

logger = logging.getLogger(__name__)

POLL_S = 0.5
# After sending a volume to a phone it reports back its own rounding (e.g.
# Android has 15 steps); reports that close to ours are that echo, not a
# change by the user. Likewise, Music Assistant reports a volume we set a
# moment later and until then still the old one.
ECHO_WINDOW_S = 3.0
ECHO_TOLERANCE = 9  # one Android volume step on the 0-127 scale
# The loudest a speaker starts at when a phone starts playing on it (0-100).
DEFAULT_START_VOLUME = 20


def to_phone(percent: int) -> int:
    return round(max(0, min(100, percent)) * 127 / 100)


def to_percent(level: int) -> int:
    return round(max(0, min(127, level)) * 100 / 127)


@dataclass(slots=True)
class PhoneState:
    transport: str
    target: str | None = None
    """The speaker (group leader) the volumes are being kept in step with."""
    phone: int | None = None
    """Last phone volume we know of (0-127)."""
    speaker: int | None = None
    """Last speaker volume we know of (0-100)."""
    echo_until: float = 0.0
    speaker_pending_until: float = 0.0
    """Until when Music Assistant may still report the volume before ours."""


Action = tuple[str, int]


def decide(
    state: PhoneState, phone_level: int | None, target: str | None, speaker_volume: int | None,
    now: float, start_volume: int = 100,
) -> list[Action]:
    """What to change: ("phone", 0-127) and/or ("speaker", 0-100) actions."""
    if phone_level is None or target is None or speaker_volume is None:
        state.target = None
        return []
    if state.target != target:
        # Started streaming to a speaker, or switched speakers: the speaker's
        # volume wins, but never above the start volume.
        state.target = target
        actions = []
        if speaker_volume > start_volume:
            speaker_volume = start_volume
            actions.append(_send_to_speaker(state, start_volume, now))
        return [*actions, _send_to_phone(state, speaker_volume, now)]
    if phone_level != state.phone:
        if now < state.echo_until and abs(phone_level - (state.phone or 0)) <= ECHO_TOLERANCE:
            state.phone = phone_level  # the phone rounding our value
            return []
        state.phone = phone_level
        level = to_percent(phone_level)
        if level == speaker_volume:
            state.speaker = level
            return []
        return [_send_to_speaker(state, level, now)]
    if speaker_volume == state.speaker:
        state.speaker_pending_until = 0.0  # Music Assistant caught up
        return []
    if now < state.speaker_pending_until:
        return []  # still the volume from before ours
    return [_send_to_phone(state, speaker_volume, now)]


def _send_to_phone(state: PhoneState, speaker_volume: int, now: float) -> Action:
    state.speaker = speaker_volume
    state.phone = to_phone(speaker_volume)
    state.echo_until = now + ECHO_WINDOW_S
    return ("phone", state.phone)


def _send_to_speaker(state: PhoneState, volume: int, now: float) -> Action:
    state.speaker = volume
    state.speaker_pending_until = now + ECHO_WINDOW_S
    return ("speaker", volume)


class VolumeSync:
    def __init__(
        self, bluetooth: BluetoothManager, receivers: Receivers, backend: PlayerBackend,
        start_volume: int = DEFAULT_START_VOLUME,
    ) -> None:
        self._bluetooth = bluetooth
        self._receivers = receivers
        self._backend = backend
        self._start_volume = start_volume
        self._states: dict[str, PhoneState] = {}
        self._changed = asyncio.Event()

    def notify(self) -> None:
        self._changed.set()

    async def run(self) -> None:
        while True:
            self._changed.clear()
            try:
                await self.sync_once()
            except (BackendError, TimeoutError, OSError) as err:
                logger.debug("Volume sync: %s", err)
            except Exception:  # noqa: BLE001 - keep syncing other phones
                logger.exception("Volume sync failed")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._changed.wait(), POLL_S)

    async def sync_once(self) -> None:
        all_speakers = {s.player_id: s for s in speakers.speakers(self._backend.players)}
        seen = set()
        for device in self._bluetooth.devices():
            receiver = self._receivers.get(device.address)
            transport = self._bluetooth.transport(device.address)
            if receiver is None or transport is None:
                continue
            seen.add(transport.path)  # keep the state across pauses
            if transport.state != "active":
                continue
            state = self._states.get(device.address)
            if state is None or state.transport != transport.path:
                # A new connection: the phone's volume doesn't count.
                state = self._states[device.address] = PhoneState(transport.path)
            uri = speakers.source_uri(receiver.source.client.identity.peer_id)
            leader = next(
                (s for s in all_speakers.values() if s.playing_uri == uri and s.synced_to is None),
                None,
            )
            volume = None if leader is None else _speaker_volume(leader)
            actions = decide(
                state, transport.volume, leader and leader.player_id, volume, time.monotonic(),
                self._start_volume,
            )
            for action in actions:
                await self._apply(device.name, transport, leader, action)
        for address in [a for a, s in self._states.items() if s.transport not in seen]:
            del self._states[address]

    async def _apply(
        self, phone: str, transport: Transport, leader: speakers.Speaker, action: tuple[str, int]
    ) -> None:
        kind, value = action
        if kind == "phone":
            logger.info("Setting %s's volume to %s's (%d%%)", phone, leader.name, to_percent(value))
            await self._bluetooth.set_phone_volume(transport.path, value)
        elif len(leader.members) > 1:
            logger.info("%s set group %s to %d%%", phone, leader.name, value)
            await self._backend.call("players/cmd/group_volume", player_id=leader.player_id, volume_level=value)
        else:
            logger.info("%s set %s to %d%%", phone, leader.name, value)
            await self._backend.call("players/cmd/volume_set", player_id=leader.player_id, volume_level=value)


def _speaker_volume(leader: speakers.Speaker) -> int | None:
    if len(leader.members) > 1 and leader.group_volume is not None:
        return leader.group_volume
    return leader.volume
