from dbus_fast import Message, MessageType, Variant

from sendspin_bluetooth.bluez import BluetoothManager, NowPlaying

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
    from sendspin_bluetooth.bluez import _unwrap_player

    props = {"Status": "paused", "Track": {"Title": Variant("s", "Numb")}}
    assert _unwrap_player(props) == {"Status": "paused", "Track": {"Title": "Numb"}}
