import pytest

from toothspin.backend import BackendError
from toothspin.speakers import plan, plan_move, quiet_start, source_uri, speakers

PIXEL = source_uri("pixel")
IPHONE = source_uri("iphone")
SQUEEZE = ["buero", "living", "bath"]


def _player(pid, *, playing=None, synced_to=None, members=(), can=(), available=True, type_="player"):
    return {
        "player_id": pid,
        "name": pid.title(),
        "type": type_,
        "available": available,
        "can_group_with": list(can) or [p for p in SQUEEZE if p != pid],
        "playback_state": "playing" if playing else "idle",
        "active_source": playing or pid,
        "synced_to": synced_to,
        "group_members": list(members),
    }


def test_lists_available_output_players_only() -> None:
    players = [
        _player("buero"),
        _player("couch", available=False),
        _player("pixel", type_="source"),
        _player("living", playing=PIXEL),
    ]
    listed = speakers(players)
    assert [s.player_id for s in listed] == ["buero", "living"]
    assert listed[1].playing_uri == PIXEL


def test_first_speaker_starts_the_input() -> None:
    assert plan([_player("buero")], PIXEL, "buero", on=True) == [
        ("player_queues/play_media", {"queue_id": "buero", "media": PIXEL})
    ]


def test_second_speaker_joins_the_group() -> None:
    players = [_player("buero", playing=PIXEL), _player("living")]
    assert plan(players, PIXEL, "living", on=True) == [
        ("players/cmd/set_members", {"target_player": "buero", "player_ids_to_add": ["living"]})
    ]


def test_incompatible_speaker_is_refused() -> None:
    players = [_player("buero", playing=PIXEL), _player("couch", can=["kitchen"])]
    with pytest.raises(BackendError, match="can't play in sync"):
        plan(players, PIXEL, "couch", on=True)


def test_untoggling_a_member_leaves_the_rest_playing() -> None:
    players = [
        _player("buero", playing=PIXEL, members=["buero", "living"]),
        _player("living", playing=PIXEL, synced_to="buero"),
    ]
    assert plan(players, PIXEL, "living", on=False) == [
        ("players/cmd/set_members", {"target_player": "buero", "player_ids_to_remove": ["living"]})
    ]


def test_untoggling_the_leader_hands_the_input_to_the_others() -> None:
    players = [
        _player("buero", playing=PIXEL, members=["buero", "living", "bath"]),
        _player("living", playing=PIXEL, synced_to="buero"),
        _player("bath", playing=PIXEL, synced_to="buero"),
    ]
    assert plan(players, PIXEL, "buero", on=False) == [
        ("players/cmd/set_members",
         {"target_player": "buero", "player_ids_to_remove": ["living", "bath"]}),
        ("player_queues/play_media", {"queue_id": "living", "media": PIXEL}),
        ("players/cmd/set_members", {"target_player": "living", "player_ids_to_add": ["bath"]}),
        ("players/cmd/stop", {"player_id": "buero"}),
    ]


def test_untoggling_the_last_speaker_stops_it() -> None:
    assert plan([_player("buero", playing=PIXEL)], PIXEL, "buero", on=False) == [
        ("players/cmd/stop", {"player_id": "buero"})
    ]


def test_taking_a_speaker_from_another_phone() -> None:
    players = [
        _player("buero", playing=PIXEL),
        _player("living", playing=IPHONE, members=["living", "bath"]),
        _player("bath", playing=IPHONE, synced_to="living"),
    ]
    assert plan(players, PIXEL, "bath", on=True) == [
        ("players/cmd/set_members", {"target_player": "living", "player_ids_to_remove": ["bath"]}),
        ("players/cmd/set_members", {"target_player": "buero", "player_ids_to_add": ["bath"]}),
    ]


def test_toggling_to_the_current_state_does_nothing() -> None:
    players = [_player("buero", playing=PIXEL), _player("living")]
    assert plan(players, PIXEL, "buero", on=True) == []
    assert plan(players, PIXEL, "living", on=False) == []


def test_moving_to_another_speaker_stops_the_old_one() -> None:
    players = [_player("buero", playing=PIXEL), _player("living")]
    assert plan_move(players, PIXEL, "living") == [
        ("player_queues/play_media", {"queue_id": "living", "media": PIXEL}),
        ("players/cmd/stop", {"player_id": "buero"}),
    ]


def test_moving_out_of_a_group_ungroups_it_first() -> None:
    players = [
        _player("buero", playing=PIXEL, members=["buero", "living", "bath"]),
        _player("living", playing=PIXEL, synced_to="buero"),
        _player("bath", playing=PIXEL, synced_to="buero"),
    ]
    assert plan_move(players, PIXEL, "bath") == [
        ("players/cmd/set_members",
         {"target_player": "buero", "player_ids_to_remove": ["living", "bath"]}),
        ("player_queues/play_media", {"queue_id": "bath", "media": PIXEL}),
        ("players/cmd/stop", {"player_id": "buero"}),
    ]


def test_moving_to_the_group_leader_drops_the_others() -> None:
    players = [
        _player("buero", playing=PIXEL, members=["buero", "living"]),
        _player("living", playing=PIXEL, synced_to="buero"),
    ]
    assert plan_move(players, PIXEL, "buero") == [
        ("players/cmd/set_members", {"target_player": "buero", "player_ids_to_remove": ["living"]})
    ]
    assert plan_move([_player("buero", playing=PIXEL)], PIXEL, "buero") == []


def test_moving_works_where_grouping_doesnt() -> None:
    players = [_player("buero", playing=PIXEL), _player("couch", can=["kitchen"])]
    assert plan_move(players, PIXEL, "couch")[0] == (
        "player_queues/play_media", {"queue_id": "couch", "media": PIXEL}
    )


def test_moving_takes_over_another_phones_speaker() -> None:
    players = [_player("buero", playing=PIXEL), _player("living", playing=IPHONE)]
    assert plan_move(players, PIXEL, "living") == [
        ("players/cmd/stop", {"player_id": "living"}),
        ("player_queues/play_media", {"queue_id": "living", "media": PIXEL}),
        ("players/cmd/stop", {"player_id": "buero"}),
    ]


def test_moving_when_not_playing_starts_there() -> None:
    assert plan_move([_player("buero")], PIXEL, "buero") == [
        ("player_queues/play_media", {"queue_id": "buero", "media": PIXEL})
    ]


def test_a_loud_speaker_is_turned_down_before_starting() -> None:
    loud = {**_player("kitchen"), "volume_control": "native", "volume_level": 97}
    assert quiet_start([loud], PIXEL, "kitchen", 20) == [
        ("players/cmd/volume_set", {"player_id": "kitchen", "volume_level": 20})
    ]
    assert quiet_start([{**loud, "volume_level": 12}], PIXEL, "kitchen", 20) == []
    # A speaker without volume control isn't touched.
    fixed = {**loud, "volume_control": "none", "volume_level": None}
    assert quiet_start([fixed], PIXEL, "kitchen", 20) == []
    # Not knowing the volume is no reason to assume it's quiet.
    assert quiet_start([{**loud, "volume_level": None}], PIXEL, "kitchen", 20) == [
        ("players/cmd/volume_set", {"player_id": "kitchen", "volume_level": 20})
    ]
    # Already playing this phone: its volume is the user's choice.
    playing = {**_player("kitchen", playing=PIXEL), "volume_control": "native", "volume_level": 97}
    assert quiet_start([playing], PIXEL, "kitchen", 20) == []


def test_applied_reflects_ma_state() -> None:
    from toothspin.speakers import _applied

    playing = [_player("buero", playing=PIXEL, members=["buero", "living"]),
               _player("living", playing=PIXEL, synced_to="buero")]
    assert _applied(playing, "player_queues/play_media", {"queue_id": "buero", "media": PIXEL})
    assert not _applied(playing, "player_queues/play_media", {"queue_id": "living", "media": IPHONE})
    assert _applied(playing, "players/cmd/set_members",
                    {"target_player": "buero", "player_ids_to_add": ["living"]})
    assert not _applied(playing, "players/cmd/set_members",
                        {"target_player": "buero", "player_ids_to_remove": ["living"]})
    assert not _applied(playing, "players/cmd/stop", {"player_id": "buero"})


class FakeMA:
    def __init__(self, players) -> None:
        self.players = players
        self.calls: list[tuple[str, dict]] = []

    async def call(self, command, **args):
        self.calls.append((command, args))
        if command == "players/cmd/volume_set":
            for p in self.players:
                if p["player_id"] == args["player_id"]:
                    p["volume_level"] = args["volume_level"]

    async def refresh(self) -> None:
        pass


def test_mute_uses_native_mute_or_emulates_it() -> None:
    import asyncio

    from toothspin.speakers import Volumes

    native = {**_player("couch"), "mute_control": "native", "volume_control": "native", "volume_level": 30}
    squeeze = {**_player("buero"), "mute_control": "none", "volume_control": "native", "volume_level": 40}
    ma = FakeMA([native, squeeze])
    volumes = Volumes(ma)  # type: ignore[arg-type]

    async def scenario() -> None:
        await volumes.set_muted("couch", True)
        assert ma.calls[-1] == ("players/cmd/volume_mute", {"player_id": "couch", "muted": True})

        await volumes.set_muted("buero", True)
        assert squeeze["volume_level"] == 0
        assert [s.muted for s in speakers(ma.players, volumes.emulated_mutes)
                if s.player_id == "buero"] == [True]
        await volumes.set_muted("buero", False)
        assert squeeze["volume_level"] == 40

        # Changing the volume while emulated-muted ends the mute.
        await volumes.set_muted("buero", True)
        await volumes.set_volume("buero", 25)
        assert squeeze["volume_level"] == 25 and "buero" not in volumes.emulated_mutes

    asyncio.run(scenario())
