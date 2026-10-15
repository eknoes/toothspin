from dbus_fast import Message, MessageType, Variant

from toothspin.bluez import BluetoothManager, NowPlaying

PLAYER_PATH = "/org/bluez/hci0/dev_84_0F_4C_90_46_AF/avrcp/player0"


def _signal(member: str, interface: str, path: str, signature: str, body: list) -> Message:
    return Message(
        message_type=MessageType.SIGNAL,
        path=path,
        interface=interface,
        member=member,
        signature=signature,
        body=body,
    )


def test_now_playing_from_avrcp() -> None:
    manager = BluetoothManager(bus=None)  # type: ignore[arg-type]
    track = {
        "Title": Variant("s", "Crawling"),
        "Artist": Variant("s", "Linkin Park"),
        "Album": Variant("s", "Hybrid Theory"),
        "Duration": Variant("u", 209000),
    }
    manager._on_message(
        _signal(
            "InterfacesAdded", "org.freedesktop.DBus.ObjectManager", "/", "oa{sa{sv}}",
            [PLAYER_PATH, {"org.bluez.MediaPlayer1": {
                "Status": Variant("s", "playing"),
                "Track": Variant("a{sv}", track),
                "Position": Variant("u", 1000),
            }}],
        )
    )
    manager._on_message(
        _signal(
            "PropertiesChanged", "org.freedesktop.DBus.Properties", PLAYER_PATH, "sa{sv}as",
            ["org.bluez.MediaPlayer1", {"Position": Variant("u", 5000)}, []],
        )
    )
    assert manager.now_playing("84:0f:4c:90:46:af") == NowPlaying(
        status="playing",
        title="Crawling",
        artist="Linkin Park",
        album="Hybrid Theory",
        duration_ms=209000,
        position_ms=5000,
    )
    assert manager.now_playing("00:11:22:33:44:55") is None


def test_unwrap_player_accepts_already_unwrapped_props() -> None:
    # GetManagedObjects results arrive with the top level already unwrapped.
    from toothspin.bluez import _unwrap_player

    props = {"Status": "paused", "Track": {"Title": Variant("s", "Numb")}}
    assert _unwrap_player(props) == {"Status": "paused", "Track": {"Title": "Numb"}}


def test_phone_connecting_on_its_own_is_disconnected() -> None:
    import asyncio

    path = "/org/bluez/hci0/dev_34_39_16_5D_41_B9"

    async def scenario() -> list[str]:
        manager = BluetoothManager(bus=None, allow_phone_connect=False)  # type: ignore[arg-type]
        refused: list[str] = []

        async def refuse(p: str) -> None:
            refused.append(p)

        manager.refuse = refuse  # type: ignore[method-assign]
        manager._devices[path] = {"Address": "34:39:16:5D:41:B9", "Paired": True}
        connected = _signal(
            "PropertiesChanged", "org.freedesktop.DBus.Properties", path, "sa{sv}as",
            ["org.bluez.Device1", {"Connected": Variant("b", True)}, []],
        )
        manager._on_message(connected)
        await asyncio.sleep(0)
        # A connection started from the receiver is kept.
        manager._connect_allowed.add(path)
        manager._on_message(connected)
        await asyncio.sleep(0)
        return refused

    assert asyncio.run(scenario()) == [path]


def test_agent_only_applies_its_policy_to_its_own_adapter() -> None:
    from dbus_fast.errors import DBusError

    from toothspin.bluez import _Agent

    manager = BluetoothManager(bus=None, adapter="hci1")  # type: ignore[arg-type]
    agent = _Agent(manager)
    ours = "/org/bluez/hci1/dev_34_39_16_5D_41_B9"
    others = "/org/bluez/hci0/dev_AA_BB_CC_DD_EE_FF"

    # Pairing window closed: our adapter refuses, HA's adapter is left alone.
    for call in (lambda d: agent.RequestConfirmation.__wrapped__(agent, d, 123456),
                 lambda d: agent.RequestAuthorization.__wrapped__(agent, d)):
        try:
            call(ours)
            raise AssertionError("pairing on our adapter should be refused")
        except DBusError:
            pass
        call(others)
    agent.AuthorizeService.__wrapped__(agent, others, "0000110a-0000-1000-8000-00805f9b34fb")


def test_phones_may_connect_on_their_own_unless_restricted() -> None:
    from toothspin.bluez import _Agent

    path = "/org/bluez/hci0/dev_34_39_16_5D_41_B9"
    strict = BluetoothManager(bus=None, allow_phone_connect=False)  # type: ignore[arg-type]
    allowing = BluetoothManager(bus=None)  # type: ignore[arg-type]  # the default
    assert not strict.connection_allowed(path)
    assert allowing.connection_allowed(path)
    # The agent accepts the phone's own A2DP connection without raising.
    _Agent(allowing).AuthorizeService.__wrapped__(
        _Agent(allowing), path, "0000110a-0000-1000-8000-00805f9b34fb"
    )


def test_pin_pairing_answers_with_the_pin_only_on_our_adapter() -> None:
    from dbus_fast.errors import DBusError

    from toothspin.bluez import _Agent

    ours = "/org/bluez/hci0/dev_34_39_16_5D_41_B9"
    others = "/org/bluez/hci1/dev_AA_BB_CC_DD_EE_FF"
    manager = BluetoothManager(bus=None, pin="482913")  # type: ignore[arg-type]
    agent = _Agent(manager)
    # No pairing window needed: the PIN is the secret.
    assert agent.RequestPinCode.__wrapped__(agent, ours) == "482913"
    assert manager.pin_pairing
    # Other adapters never get our PIN.
    assert agent.RequestPinCode.__wrapped__(agent, others) == "0000"
    # Pairing without a PIN (Just Works) still needs the window.
    try:
        agent.RequestConfirmation.__wrapped__(agent, ours, 123456)
        raise AssertionError("Just Works pairing should need the window")
    except DBusError:
        pass
    # Without BT_PIN, PIN requests need the window too.
    plain = _Agent(BluetoothManager(bus=None))  # type: ignore[arg-type]
    try:
        plain.RequestPinCode.__wrapped__(plain, ours)
        raise AssertionError("PIN request without BT_PIN should need the window")
    except DBusError:
        pass


def test_reconnects_once_when_the_phone_plays_but_not_to_us(monkeypatch) -> None:  # noqa: ANN001
    import asyncio

    from toothspin import bluez

    monkeypatch.setattr(bluez, "ROUTING_POLL_S", 0.01)
    monkeypatch.setattr(bluez, "ROUTING_STUCK_S", 0.05)
    monkeypatch.setattr(bluez, "ROUTING_CHECK_S", 0.5)
    monkeypatch.setattr(bluez, "ROUTING_RECONNECT_GAPS_S", (0.01, 0.02))
    device = "/org/bluez/hci0/dev_34_39_16_5D_41_B9"

    async def scenario(transport_state: str, player_status: str) -> list[str]:
        calls: list[str] = []

        async def call(_bus, _service, _path, _iface, member, *args):  # noqa: ANN001, ANN002
            calls.append(member)
            await asyncio.sleep(0)

        monkeypatch.setattr(bluez.dbus, "call", call)
        monkeypatch.setattr(bluez.asyncio, "sleep", _fast_sleep)
        manager = BluetoothManager(bus=None)  # type: ignore[arg-type]
        manager._devices[device] = {"Address": "34:39:16:5D:41:B9", "Paired": True, "Connected": True}
        manager._transports[device + "/fd0"] = {"State": transport_state}
        manager._players[device + "/avrcp/player0"] = {"Status": player_status}
        await manager.connect_device("34:39:16:5D:41:B9")
        while manager._routing_tasks:
            await asyncio.gather(*list(manager._routing_tasks.values()))
        return calls

    # Playing, but the stream to us never starts: two reconnects, then it
    # gives up.
    assert asyncio.run(scenario("idle", "playing")) == [
        "Connect", "Disconnect", "Connect", "Disconnect", "Connect"
    ]
    # Streaming to us, or simply paused: leave it alone.
    assert asyncio.run(scenario("active", "playing")) == ["Connect"]
    assert asyncio.run(scenario("idle", "paused")) == ["Connect"]


_real_sleep = __import__("asyncio").sleep


async def _fast_sleep(seconds: float) -> None:
    await _real_sleep(min(seconds, 0.01))


def test_pressing_connect_wins_over_a_pending_reconnect(monkeypatch) -> None:  # noqa: ANN001
    import asyncio

    from toothspin import bluez

    monkeypatch.setattr(bluez, "ROUTING_POLL_S", 0.01)
    monkeypatch.setattr(bluez, "ROUTING_STUCK_S", 0.05)
    address, device = "34:39:16:5D:41:B9", "/org/bluez/hci0/dev_34_39_16_5D_41_B9"

    async def scenario() -> list[str]:
        calls: list[str] = []
        manager = BluetoothManager(bus=None)  # type: ignore[arg-type]

        async def call(_bus, _service, _path, _iface, member, *args):  # noqa: ANN001, ANN002
            calls.append(member)
            manager._devices[device]["Connected"] = member == "Connect"

        monkeypatch.setattr(bluez.dbus, "call", call)
        manager._devices[device] = {"Address": address, "Paired": True, "Connected": False}
        manager._transports[device + "/fd0"] = {"State": "idle"}
        manager._players[device + "/avrcp/player0"] = {"Status": "playing"}
        await manager.connect_device(address)
        async with asyncio.timeout(5):
            while not manager.reconnecting(address):  # waiting out the 5 s gap
                await asyncio.sleep(0.01)
        manager._transports[device + "/fd0"]["State"] = "active"  # it'll work now
        await manager.connect_device(address)  # the user presses Connect
        await asyncio.sleep(0.2)
        assert not manager.reconnecting(address)
        for task in list(manager._routing_tasks.values()):
            task.cancel()
        return calls

    # No second, automatic Connect after the user's.
    assert asyncio.run(scenario()) == ["Connect", "Disconnect", "Connect"]


def test_connect_waits_for_an_attempt_in_progress(monkeypatch) -> None:  # noqa: ANN001
    import asyncio

    from dbus_fast.errors import DBusError

    from toothspin import bluez

    address, device = "34:39:16:5D:41:B9", "/org/bluez/hci0/dev_34_39_16_5D_41_B9"

    async def scenario() -> bool:
        manager = BluetoothManager(bus=None)  # type: ignore[arg-type]
        manager._devices[device] = {"Address": address, "Paired": True, "Connected": False}

        async def call(*_args):  # noqa: ANN002
            # Someone else's attempt, which succeeds a moment later.
            asyncio.get_running_loop().call_later(
                0.1, manager._devices[device].__setitem__, "Connected", True
            )
            raise DBusError("org.bluez.Error.InProgress", "In Progress")

        monkeypatch.setattr(bluez.dbus, "call", call)
        monkeypatch.setattr(bluez, "ROUTING_RECONNECT_GAPS_S", ())
        await manager.connect_device(address)
        return manager._devices[device]["Connected"]

    assert asyncio.run(scenario())


def test_connects_a_freshly_paired_phone_that_didnt_connect(monkeypatch) -> None:  # noqa: ANN001
    import asyncio

    from toothspin import bluez

    monkeypatch.setattr(bluez, "CONNECT_AFTER_PAIRING_S", 0.01)
    monkeypatch.setattr(bluez, "ROUTING_RECONNECT_GAPS_S", ())
    device = "/org/bluez/hci0/dev_34_39_16_5D_41_B9"

    async def scenario(connected: bool) -> list[str]:
        calls: list[str] = []

        async def call(_bus, _service, _path, _iface, member, *args):  # noqa: ANN001, ANN002
            calls.append(member)

        monkeypatch.setattr(bluez.dbus, "call", call)
        manager = BluetoothManager(bus=None)  # type: ignore[arg-type]
        manager._devices[device] = {"Address": "34:39:16:5D:41:B9", "Paired": True,
                                    "Connected": connected}
        await manager._on_paired(device)
        return calls

    # The phone's own connection broke down while pairing: finish it from here.
    assert asyncio.run(scenario(connected=False)) == ["Connect"]
    # It connected by itself: nothing to do.
    assert asyncio.run(scenario(connected=True)) == []
