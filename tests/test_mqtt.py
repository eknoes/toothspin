import asyncio
import json
import os
import shutil
import socket
import subprocess
from types import SimpleNamespace

import aiomqtt
import pytest

from toothspin import mqtt, speakers
from toothspin.mqtt import OFF, SEVERAL, Broker, Command, Phone, broker_from_url, build

NODE = "toothspin_001122334455"
BASE = f"toothspin/{NODE}"
PHONE = Phone("AA:BB:CC:00:00:01", "Pixel", "sendspin_source://audio_source/pixel")
A = "aabbcc000001"


def player(player_id, name=None, playing=None, synced_to=None, members=(), group_with=()):  # noqa: ANN001, ANN201
    return {
        "player_id": player_id, "name": name or player_id.title(), "type": "player", "available": True,
        "playback_state": "playing" if playing else "idle", "active_source": playing,
        "synced_to": synced_to, "group_members": list(members), "can_group_with": list(group_with),
    }


def speaker_list(*players):  # noqa: ANN002, ANN201
    return speakers.speakers(list(players))


def config(entities, component, object_id):  # noqa: ANN001, ANN201
    return json.loads(entities.configs[f"homeassistant/{component}/{NODE}/{object_id}/config"])


def switch_key(entities, name):  # noqa: ANN001, ANN201
    for topic, payload in entities.configs.items():
        if "/switch/" in topic and json.loads(payload)["name"] == name:
            return json.loads(payload)["state_topic"]
    raise KeyError(name)


def test_pairing_button_and_state() -> None:
    entities = build(NODE, [], None, False, pairing_open=True)
    assert config(entities, "button", "pairing")["command_topic"] == f"{BASE}/cmd/pairing"
    assert entities.commands[f"{BASE}/cmd/pairing"] == Command("pair")
    assert entities.states[f"{BASE}/pairing"] == "ON"
    # No speaker control, no phone entities.
    assert not any("/select/" in t or "/switch/" in t for t in entities.configs)


def test_dropdown_and_switches_follow_what_plays() -> None:
    entities = build(NODE, [PHONE], speaker_list(
        player("kitchen", playing=PHONE.uri), player("bath"),
    ), True, False)
    select = config(entities, "select", f"{A}_speaker")
    assert select["options"] == [OFF, "Bath", "Kitchen"]
    assert entities.states[f"{BASE}/{A}/speaker"] == "Kitchen"
    assert entities.states[switch_key(entities, "Kitchen")] == "ON"
    assert entities.states[switch_key(entities, "Bath")] == "OFF"
    assert select["device"]["via_device"] == NODE
    command = entities.commands[f"{BASE}/cmd/{A}/speaker"]
    assert command.options == {OFF: None, "Bath": "bath", "Kitchen": "kitchen"}


def test_several_speakers_and_those_that_cant_join() -> None:
    entities = build(NODE, [PHONE], speaker_list(
        player("kitchen", playing=PHONE.uri, members=("kitchen", "bath"), group_with=("bath",)),
        player("bath", playing=PHONE.uri, synced_to="kitchen"),
        player("garage"),
    ), True, False)
    assert config(entities, "select", f"{A}_speaker")["options"][-1] == SEVERAL
    assert entities.states[f"{BASE}/{A}/speaker"] == SEVERAL
    garage = switch_key(entities, "Garage")
    assert entities.states[garage] == "OFF"
    assert entities.states[f"{garage}/available"] == "offline"
    assert entities.states[f"{switch_key(entities, 'Bath')}/available"] == "online"


def test_hidden_and_same_named_speakers() -> None:
    phone = Phone(PHONE.address, PHONE.name, PHONE.uri, frozenset({"hidden", "hidden_playing"}))
    entities = build(NODE, [phone], speaker_list(
        player("a", "Echo"), player("b", "Echo"), player("hidden"),
        player("hidden_playing", "Loud", playing="sendspin_source://audio_source/pixel"),
    ), True, False)
    options = config(entities, "select", f"{A}_speaker")["options"]
    assert options == [OFF, "Echo", "Echo (2)", "Loud"]


def test_configs_have_one_kind_of_availability() -> None:
    entities = build(NODE, [PHONE], speaker_list(player("kitchen")), True, False)
    for payload in entities.configs.values():
        parsed = json.loads(payload)
        assert ("availability" in parsed) != ("availability_topic" in parsed)


def test_speakers_stay_while_the_backend_is_down() -> None:
    entities = build(NODE, [PHONE], speaker_list(player("kitchen")), False, False)
    assert entities.states[f"{BASE}/{A}/available"] == "offline"
    assert switch_key(entities, "Kitchen")


def test_broker_url() -> None:
    assert broker_from_url("mqtt://u%40x:p@host") == Broker("host", 1883, "u@x", "p")
    assert broker_from_url("mqtts://host:9000") == Broker("host", 9000, tls=True)
    with pytest.raises(ValueError):
        broker_from_url("http://host")


class FakeRouter:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def toggle(self, uri, player_id, on):  # noqa: ANN001, ANN201
        self.calls.append(("toggle", player_id, on))
        return True

    async def move(self, uri, player_id):  # noqa: ANN001, ANN201
        self.calls.append(("move", player_id))

    async def stop(self, uri):  # noqa: ANN001, ANN201
        self.calls.append(("stop",))


def fakes(players: list[dict]) -> tuple[SimpleNamespace, SimpleNamespace, SimpleNamespace]:
    pairing: list[float] = []

    async def open_pairing(seconds: float) -> None:
        pairing.append(seconds)

    bluetooth = SimpleNamespace(
        address="00:11:22:33:44:55", pairing_remaining=None, opened=pairing,
        devices=lambda: [SimpleNamespace(address=PHONE.address, name="Pixel", connected=True)],
        open_pairing=open_pairing,
    )
    source = SimpleNamespace(client=SimpleNamespace(identity=SimpleNamespace(peer_id="pixel")))
    receivers = SimpleNamespace(
        get=lambda address: SimpleNamespace(source=source) if address == PHONE.address else None,
        hidden_speakers=lambda address: [],
    )
    backend = SimpleNamespace(connected=True, players=players)
    return bluetooth, receivers, backend


def test_commands_go_through_the_router() -> None:
    bluetooth, receivers, backend = fakes([player("kitchen"), player("bath")])
    router = FakeRouter()
    bridge = mqtt.MqttBridge(Broker("x"), bluetooth, receivers, backend, router, 90)

    async def scenario() -> None:
        await bridge.execute(Command("pair"), "PRESS")
        await bridge.execute(Command("switch", PHONE.address, player_id="bath"), "ON")
        await bridge.execute(Command("switch", PHONE.address, player_id="bath"), "garbage")
        select = Command("select", PHONE.address, options={OFF: None, "Kitchen": "kitchen"})
        await bridge.execute(select, "Kitchen")
        await bridge.execute(select, OFF)
        await bridge.execute(select, SEVERAL)

    asyncio.run(scenario())
    assert bluetooth.opened == [90]
    assert router.calls == [("toggle", "bath", True), ("move", "kitchen"), ("stop",)]


def test_router_stop_takes_followers_off_first(monkeypatch) -> None:
    uri = PHONE.uri
    backend = SimpleNamespace(players=[
        player("kitchen", playing=uri, members=("kitchen", "bath")),
        player("bath", playing=uri, synced_to="kitchen"),
        player("garage"),
    ])

    async def refresh() -> None:
        pass

    backend.refresh = refresh
    calls = []

    async def fake_toggle(_backend, _uri, player_id, on, start_volume=100):  # noqa: ANN001, ANN202, ARG001
        calls.append((player_id, on))

    monkeypatch.setattr(speakers, "toggle", fake_toggle)
    asyncio.run(speakers.Router(backend).stop(uri))
    assert calls == [("bath", False), ("kitchen", False)]


@pytest.fixture
def broker():  # noqa: ANN201
    if shutil.which("mosquitto") is None:
        if os.environ.get("CI"):
            pytest.fail("CI installs mosquitto, but it isn't there")
        pytest.skip("needs mosquitto")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    process = subprocess.Popen(["mosquitto", "-p", str(port)], stderr=subprocess.DEVNULL)  # noqa: S603, S607
    for _ in range(50):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.1).close()
            break
        except OSError:
            subprocess.run(["sleep", "0.05"], check=False)  # noqa: S603, S607
    yield Broker("127.0.0.1", port)
    process.terminate()
    process.wait()


@pytest.mark.timeout(20)
def test_against_a_broker(broker) -> None:  # noqa: ANN001
    uri = "sendspin_source://audio_source/pixel"
    bluetooth, receivers, backend = fakes([player("kitchen", playing=uri), player("bath")])
    router = FakeRouter()
    bridge = mqtt.MqttBridge(broker, bluetooth, receivers, backend, router, 120)
    stale = f"homeassistant/switch/{NODE}/{A}_gone/config"
    stale_state = f"{BASE}/{A}/gone"

    async def scenario() -> dict[str, str]:
        async with aiomqtt.Client(broker.host, broker.port) as ha:
            # Left over from before a restart: an entity that's gone since.
            await ha.publish(stale, json.dumps({"state_topic": stale_state}), retain=True)
            await ha.publish(stale_state, "ON", retain=True)
            task = asyncio.create_task(bridge.run())
            await asyncio.sleep(2.5)
            await ha.subscribe(f"{BASE}/cmd/#")
            await ha.publish(f"{BASE}/cmd/{A}/speaker", "Bath")
            await asyncio.sleep(0.5)
            seen: dict[str, str] = {}
            async with aiomqtt.Client(broker.host, broker.port) as fresh:
                await fresh.subscribe("homeassistant/#")
                await fresh.subscribe("toothspin/#")
                try:
                    async with asyncio.timeout(1.0):
                        async for message in fresh.messages:
                            seen[str(message.topic)] = message.payload.decode()
                except TimeoutError:
                    pass
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            return seen

    seen = asyncio.run(scenario())
    assert seen[f"{BASE}/status"] == "online"
    assert seen[f"{BASE}/{A}/speaker"] == "Kitchen"
    assert f"homeassistant/select/{NODE}/{A}_speaker/config" in seen
    assert stale not in seen and stale_state not in seen
    assert router.calls == [("move", "bath")]
