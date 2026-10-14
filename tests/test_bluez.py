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
        manager = BluetoothManager(bus=None)  # type: ignore[arg-type]
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


def test_phones_may_connect_on_their_own_when_allowed() -> None:
    from toothspin.bluez import _Agent

    path = "/org/bluez/hci0/dev_34_39_16_5D_41_B9"
    strict = BluetoothManager(bus=None)  # type: ignore[arg-type]
    allowing = BluetoothManager(bus=None, allow_phone_connect=True)  # type: ignore[arg-type]
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
