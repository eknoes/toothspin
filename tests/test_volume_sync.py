from toothspin.volume_sync import ECHO_WINDOW_S, PhoneState, decide, to_percent, to_phone


def test_after_connecting_the_speaker_volume_wins() -> None:
    state = PhoneState("t")
    # The phone arrives with its own volume (100/127); the speaker is at 30%.
    assert decide(state, 100, "buero", 30, now=0) == ("phone", to_phone(30))


def test_phone_volume_buttons_set_the_speaker() -> None:
    state = PhoneState("t")
    decide(state, 100, "buero", 30, now=0)
    sent = state.phone
    # Long after the echo window, the user presses volume up on the phone.
    assert decide(state, sent + 17, "buero", 30, now=10) == ("speaker", to_percent(sent + 17))
    # The speaker follows; nothing more to do once MA reports it.
    assert decide(state, sent + 17, "buero", to_percent(sent + 17), now=11) is None


def test_speaker_changes_elsewhere_reach_the_phone() -> None:
    state = PhoneState("t")
    decide(state, 100, "buero", 30, now=0)
    assert decide(state, state.phone, "buero", 55, now=10) == ("phone", to_phone(55))


def test_phone_rounding_right_after_a_push_is_not_a_change() -> None:
    state = PhoneState("t")
    decide(state, 100, "buero", 30, now=0)  # sends 38/127
    # The phone snaps to its nearest step (34) and reports that back.
    assert decide(state, 34, "buero", 30, now=0.5) is None
    # A real change within the window, beyond one step, still counts.
    assert decide(state, 60, "buero", 30, now=1) == ("speaker", to_percent(60))
    # After the window, even a small change counts.
    assert decide(state, 64, "buero", to_percent(60), now=ECHO_WINDOW_S + 5) == ("speaker", to_percent(64))


def test_switching_speakers_resyncs_the_phone() -> None:
    state = PhoneState("t")
    decide(state, 100, "buero", 30, now=0)
    assert decide(state, state.phone, "living", 70, now=10) == ("phone", to_phone(70))


def test_nothing_without_a_speaker_or_phone_volume() -> None:
    state = PhoneState("t")
    assert decide(state, 100, None, None, now=0) is None
    assert decide(state, None, "buero", 30, now=0) is None
    # Once a speaker is chosen, it wins.
    assert decide(state, 100, "buero", 30, now=1) == ("phone", to_phone(30))


def test_scale_round_trips() -> None:
    assert to_phone(0) == 0 and to_phone(100) == 127
    assert all(to_percent(to_phone(p)) == p for p in range(101))


def test_sync_applies_to_phone_single_speaker_and_group() -> None:
    import asyncio
    from types import SimpleNamespace

    from toothspin.bluez import BluetoothDevice, Transport
    from toothspin.speakers import source_uri
    from toothspin.volume_sync import VolumeSync

    phone = BluetoothDevice("AA:AA:AA:AA:AA:AA", "Pixel", paired=True, trusted=False, connected=True)
    uri = source_uri("pixel-id")

    class FakeBluetooth:
        def __init__(self) -> None:
            self.transport_state = Transport("/t", "active", 100)
            self.phone_volumes: list[int] = []

        def devices(self):
            return [phone]

        def transport(self, address):
            return self.transport_state

        async def set_phone_volume(self, path, level):
            self.phone_volumes.append(level)
            self.transport_state = Transport(path, self.transport_state.state, level)

    class FakeReceivers:
        def get(self, address):
            return SimpleNamespace(source=SimpleNamespace(client=SimpleNamespace(
                identity=SimpleNamespace(peer_id="pixel-id"))))

    def player(pid, **extra):
        return {"player_id": pid, "name": pid, "type": "player", "available": True,
                "playback_state": "playing", "active_source": uri, "synced_to": None,
                "group_members": [], "volume_level": 30, "group_volume": 30, **extra}

    class FakeMA:
        players = [player("buero")]
        calls: list = []

        async def call(self, command, **args):
            self.calls.append((command, args))

    bluetooth, ma = FakeBluetooth(), FakeMA()
    sync = VolumeSync(bluetooth, FakeReceivers(), ma)  # type: ignore[arg-type]

    async def scenario() -> None:
        await sync.sync_once()
        assert bluetooth.phone_volumes == [to_phone(30)]  # speaker wins on connect

        sync._states[phone.address].echo_until = 0  # skip the echo window
        bluetooth.transport_state = Transport("/t", "active", 90)  # phone volume up
        await sync.sync_once()
        assert ma.calls[-1] == ("players/cmd/volume_set", {"player_id": "buero", "volume_level": to_percent(90)})

        # Now playing on a group led by buero: the group volume is used.
        ma.players = [player("buero", group_members=["buero", "living"], group_volume=to_percent(90)),
                      player("living", synced_to="buero")]
        bluetooth.transport_state = Transport("/t", "active", 40)
        await sync.sync_once()
        assert ma.calls[-1] == ("players/cmd/group_volume", {"player_id": "buero", "volume_level": to_percent(40)})

        # While the phone is paused, nothing is changed.
        calls = len(ma.calls)
        bluetooth.transport_state = Transport("/t", "idle", 10)
        await sync.sync_once()
        assert len(ma.calls) == calls

    asyncio.run(scenario())
