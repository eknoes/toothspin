"""Home Assistant entities over MQTT: pairing, and which speakers a phone plays on.

Published with MQTT discovery, so they show up in Home Assistant by
themselves once its MQTT integration runs:

- ToothSpin: a button that opens the pairing window, and whether it's open.
- Each phone: a dropdown that plays it on just one speaker (or none), and a
  switch per speaker that adds it to the phone's group or takes it out.

The entities do what the web UI's buttons do, through the same routing, so
both show the same and quick changes from either happen one after another.
Speakers are the backend's (``speakers.speakers``): with the standalone
server its fixed speaker groups show as one speaker.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from urllib.parse import unquote, urlsplit

import aiomqtt

from . import speakers
from .backend import BackendError
from . import build_info

if TYPE_CHECKING:
    from .backend import PlayerBackend
    from .bluez import BluetoothManager
    from .receivers import Receivers

logger = logging.getLogger(__name__)

DISCOVERY_PREFIX = "homeassistant"
# Home Assistant announces itself here when it (re)starts.
HA_STATUS = f"{DISCOVERY_PREFIX}/status"
SYNC_S = 1.0
RETRY_S = 5.0
RETRY_MAX_S = 60.0
OFF = "Off"
# Shown while a phone plays on more than one speaker; picking it does nothing.
SEVERAL = "Several speakers"


@dataclass(frozen=True, slots=True)
class Broker:
    host: str
    port: int = 1883
    username: str | None = None
    password: str | None = None
    tls: bool = False


def broker_from_url(url: str) -> Broker:
    """mqtt://user:password@host:1883, or mqtts:// for TLS."""
    parts = urlsplit(url)
    if parts.scheme not in ("mqtt", "mqtts") or not parts.hostname:
        raise ValueError(f"not an mqtt:// or mqtts:// URL: {url}")
    tls = parts.scheme == "mqtts"
    return Broker(
        host=parts.hostname,
        port=parts.port or (8883 if tls else 1883),
        username=unquote(parts.username) if parts.username else None,
        password=unquote(parts.password) if parts.password else None,
        tls=tls,
    )


@dataclass(frozen=True, slots=True)
class Phone:
    address: str
    name: str
    uri: str
    """Its input's source URI, as speakers report what they play."""
    hidden: frozenset[str] = frozenset()
    """Speakers hidden on its card in the web UI."""


@dataclass(frozen=True, slots=True)
class Command:
    kind: str
    """pair, select or switch."""
    address: str = ""
    player_id: str = ""
    options: dict[str, str | None] = field(default_factory=dict)
    """For select: option -> player_id (None: off)."""


@dataclass(slots=True)
class Entities:
    configs: dict[str, str] = field(default_factory=dict)
    """Discovery topic -> config (JSON)."""
    states: dict[str, str] = field(default_factory=dict)
    commands: dict[str, Command] = field(default_factory=dict)


def node_id(adapter_address: str) -> str:
    return "toothspin_" + adapter_address.replace(":", "").lower()


def _key(player_id: str) -> str:
    """A topic- and ID-safe key for a player ID, which may hold anything."""
    slug = re.sub(r"[^a-z0-9]+", "_", player_id.lower()).strip("_")[:32]
    return f"{slug}_{hashlib.sha256(player_id.encode()).hexdigest()[:6]}"


def _unique_names(names: list[tuple[str, str]]) -> dict[str, str]:
    """player_id -> option; speakers with the same name get a number."""
    taken: set[str] = {OFF, SEVERAL}
    result = {}
    for player_id, name in names:
        option, n = name, 2
        while option in taken:
            option, n = f"{name} ({n})", n + 1
        taken.add(option)
        result[player_id] = option
    return result


def _on(value: bool) -> str:
    return "ON" if value else "OFF"


def build(
    node: str,
    phones: list[Phone],
    all_speakers: list[speakers.Speaker] | None,
    speakers_known: bool,
    pairing_open: bool,
    configuration_url: str | None = None,
) -> Entities:
    """Every entity's discovery config, state and command topic.

    ``all_speakers`` None: no speaker control (no backend). ``speakers_known``
    False: the backend is down, so the speakers' entities show as unavailable
    rather than vanishing.
    """
    base = f"toothspin/{node}"
    online = f"{base}/status"
    entities = Entities()
    bridge_device: dict[str, Any] = {
        "identifiers": [node],
        "name": "ToothSpin",
        "manufacturer": "ToothSpin",
        "model": "Bluetooth audio receiver",
        "sw_version": build_info().get("version"),
    }
    if configuration_url:
        bridge_device["configuration_url"] = configuration_url
    origin = {"name": "ToothSpin", "url": "https://github.com/eknoes/toothspin"}

    def add(component: str, object_id: str, config: dict[str, Any]) -> None:
        config = {"unique_id": f"{node}_{object_id}", "origin": origin, **config}
        config.setdefault("availability_topic", online)
        topic = f"{DISCOVERY_PREFIX}/{component}/{node}/{object_id}/config"
        entities.configs[topic] = json.dumps(config, sort_keys=True)

    add("button", "pairing", {
        "name": "Pair a phone",
        "icon": "mdi:bluetooth-connect",
        "command_topic": f"{base}/cmd/pairing",
        "device": bridge_device,
    })
    entities.commands[f"{base}/cmd/pairing"] = Command("pair")
    add("binary_sensor", "pairing_open", {
        "name": "Pairing",
        "icon": "mdi:bluetooth-settings",
        "state_topic": f"{base}/pairing",
        "device": bridge_device,
    })
    entities.states[f"{base}/pairing"] = _on(pairing_open)
    if all_speakers is None:
        return entities

    for phone in phones:
        a = phone.address.replace(":", "").lower()
        device = {
            "identifiers": [f"{node}_{a}"],
            "name": phone.name,
            "model": "Phone over Bluetooth",
            "via_device": node,
        }
        phone_available = f"{base}/{a}/available"
        entities.states[phone_available] = "online" if speakers_known else "offline"
        availability = {
            "availability": [{"topic": online}, {"topic": phone_available}],
            "availability_mode": "all",
        }
        playing = [s for s in all_speakers if s.playing_uri == phone.uri]
        shown = [s for s in all_speakers if s.player_id not in phone.hidden or s in playing]
        options = _unique_names([(s.player_id, s.name) for s in shown])
        leader = next((s for s in playing if s.synced_to is None), None)

        choices = [OFF, *options.values()]
        if not playing:
            current = OFF
        elif len(playing) == 1:
            current = options[playing[0].player_id]
        else:
            current = SEVERAL
            choices.append(SEVERAL)
        add("select", f"{a}_speaker", {
            "name": "Speaker",
            "icon": "mdi:speaker",
            "options": choices,
            "command_topic": f"{base}/cmd/{a}/speaker",
            "state_topic": f"{base}/{a}/speaker",
            "device": device,
            **availability,
        })
        entities.states[f"{base}/{a}/speaker"] = current
        entities.commands[f"{base}/cmd/{a}/speaker"] = Command(
            "select", phone.address,
            options={OFF: None, **{option: pid for pid, option in options.items()}},
        )

        for speaker in shown:
            k = _key(speaker.player_id)
            on = speaker in playing
            # Only speakers that can play in sync with the group can join it.
            can_join = on or leader is None or speaker.player_id in leader.can_group_with
            available = f"{base}/{a}/{k}/available"
            add("switch", f"{a}_{k}", {
                "name": options[speaker.player_id],
                "icon": "mdi:speaker-multiple",
                "command_topic": f"{base}/cmd/{a}/{k}",
                "state_topic": f"{base}/{a}/{k}",
                "device": device,
                "availability": [*availability["availability"], {"topic": available}],
                "availability_mode": "all",
            })
            entities.states[f"{base}/{a}/{k}"] = _on(on)
            entities.states[available] = "online" if can_join else "offline"
            entities.commands[f"{base}/cmd/{a}/{k}"] = Command(
                "switch", phone.address, player_id=speaker.player_id
            )
    return entities


class MqttBridge:
    """Keeps the entities in step with ToothSpin and carries out their commands."""

    def __init__(
        self,
        broker: Broker,
        bluetooth: BluetoothManager,
        receivers: Receivers,
        backend: PlayerBackend | None,
        router: speakers.Router | None,
        pairing_seconds: float,
        configuration_url: str | None = None,
    ) -> None:
        self._broker = broker
        self._bluetooth = bluetooth
        self._receivers = receivers
        self._backend = backend
        self._router = router
        self._pairing_seconds = pairing_seconds
        self._configuration_url = configuration_url
        self._node = ""
        # The speakers last seen while the backend was up, kept while it's down.
        self._speakers: list[speakers.Speaker] = []
        self._entities = Entities()
        self._published: dict[str, str] = {}
        # Our discovery configs the broker holds (retained), e.g. from before a restart.
        self._retained: dict[str, str] = {}
        self._changed = asyncio.Event()
        self._tasks: set[asyncio.Task[None]] = set()

    def notify(self) -> None:
        self._changed.set()

    async def run(self) -> None:
        self._node = node_id(self._bluetooth.address or "unknown")
        delay = RETRY_S
        while True:
            try:
                async with self._client() as client:
                    logger.info("Connected to MQTT broker %s:%d", self._broker.host, self._broker.port)
                    delay = RETRY_S
                    await self._session(client)
            except aiomqtt.MqttError as err:
                logger.warning("MQTT broker %s:%d: %s; retrying in %.0f s",
                               self._broker.host, self._broker.port, err, delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, RETRY_MAX_S)

    def _client(self) -> aiomqtt.Client:
        return aiomqtt.Client(
            self._broker.host, self._broker.port,
            username=self._broker.username, password=self._broker.password,
            identifier=self._node,
            will=aiomqtt.Will(self._online_topic, "offline", qos=1, retain=True),
            tls_params=aiomqtt.TLSParameters() if self._broker.tls else None,
        )

    @property
    def _online_topic(self) -> str:
        return f"toothspin/{self._node}/status"

    async def _session(self, client: aiomqtt.Client) -> None:
        self._published.clear()
        self._retained.clear()
        await client.subscribe(f"{DISCOVERY_PREFIX}/+/{self._node}/+/config")
        await client.subscribe(f"toothspin/{self._node}/cmd/#")
        await client.subscribe(HA_STATUS)
        await client.publish(self._online_topic, "online", qos=1, retain=True)
        sync = asyncio.create_task(self._keep_synced(client))
        try:
            async for message in client.messages:
                self._on_message(str(message.topic), _text(message.payload))
        finally:
            sync.cancel()
            await asyncio.gather(sync, return_exceptions=True)

    async def _keep_synced(self, client: aiomqtt.Client) -> None:
        while True:
            await self.sync(client)
            self._changed.clear()
            try:
                await asyncio.wait_for(self._changed.wait(), SYNC_S)
            except TimeoutError:
                pass

    def _current(self) -> Entities:
        phones = []
        for device in self._bluetooth.devices():
            receiver = self._receivers.get(device.address)
            if receiver is None:
                continue
            phones.append(Phone(
                device.address, device.name,
                speakers.source_uri(receiver.source.client.identity.peer_id),
                frozenset(self._receivers.hidden_speakers(device.address)),
            ))
        known = self._backend is not None and self._backend.connected
        if known:
            assert self._backend is not None
            self._speakers = speakers.speakers(self._backend.players)
        return build(
            self._node, phones, self._speakers if self._backend else None, known,
            self._bluetooth.pairing_remaining is not None, self._configuration_url,
        )

    async def sync(self, client: aiomqtt.Client) -> None:
        """Publish what changed; remove entities that are gone."""
        self._entities = self._current()
        wanted = {**self._entities.configs, **self._entities.states}
        for topic in sorted(self._retained.keys() - self._entities.configs.keys()):
            # The entity is gone: its config, and the states the broker keeps for it.
            for stale in (topic, *_state_topics(self._retained.pop(topic))):
                if stale not in wanted:
                    await client.publish(stale, "", qos=1, retain=True)
        # Configs first, so Home Assistant knows an entity before its state.
        for topic, payload in sorted(wanted.items(), key=lambda kv: kv[0] not in self._entities.configs):
            if self._published.get(topic) != payload:
                await client.publish(topic, payload, qos=1, retain=True)
                self._published[topic] = payload
        for topic in self._published.keys() - wanted.keys():
            del self._published[topic]

    def _on_message(self, topic: str, payload: str) -> None:
        if topic == HA_STATUS:
            if payload == "online":
                # Home Assistant restarted: announce everything again.
                self._published.clear()
                self.notify()
        elif topic.startswith(f"{DISCOVERY_PREFIX}/"):
            if payload:
                self._retained[topic] = payload
            else:
                self._retained.pop(topic, None)
        elif (command := self._entities.commands.get(topic)) is not None:
            task = asyncio.create_task(self._run(command, payload))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def _run(self, command: Command, payload: str) -> None:
        try:
            await self.execute(command, payload)
        except (BackendError, TimeoutError) as err:
            logger.warning("Home Assistant's command failed: %s", err)
        finally:
            # Show what actually happened, also when nothing did.
            self._published = {t: p for t, p in self._published.items() if t in self._entities.configs}
            self.notify()

    async def execute(self, command: Command, payload: str) -> None:
        if command.kind == "pair":
            await self._bluetooth.open_pairing(self._pairing_seconds)
            return
        receiver = self._receivers.get(command.address)
        if receiver is None or self._router is None:
            return
        uri = speakers.source_uri(receiver.source.client.identity.peer_id)
        if command.kind == "switch" and payload in ("ON", "OFF"):
            await self._router.toggle(uri, command.player_id, payload == "ON")
        elif command.kind == "select" and payload in command.options:
            player_id = command.options[payload]
            if player_id is None:
                await self._router.stop(uri)
            else:
                await self._router.move(uri, player_id)


def _state_topics(config: str) -> list[str]:
    """The topics an entity's config has ToothSpin publish to (not its commands)."""
    try:
        parsed = json.loads(config)
    except ValueError:
        return []
    if not isinstance(parsed, dict):
        return []
    topics = [parsed.get("state_topic")]
    topics += [a.get("topic") for a in parsed.get("availability") or () if isinstance(a, dict)]
    # The bridge's status belongs to the will and outlives any one entity.
    return [
        t for t in topics
        if isinstance(t, str) and t.startswith("toothspin/") and not t.endswith("/status")
    ]


def _text(payload: Any) -> str:
    if isinstance(payload, bytes | bytearray):
        return payload.decode(errors="replace")
    return "" if payload is None else str(payload)

