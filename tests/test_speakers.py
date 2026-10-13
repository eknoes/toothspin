import pytest

from sendspin_bluetooth.ma import MusicAssistantError
from sendspin_bluetooth.speakers import plan, source_uri, speakers

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
    with pytest.raises(MusicAssistantError, match="can't play in sync"):
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


def test_applied_reflects_ma_state() -> None:
    from sendspin_bluetooth.speakers import _applied

    playing = [_player("buero", playing=PIXEL, members=["buero", "living"]),
               _player("living", playing=PIXEL, synced_to="buero")]
    assert _applied(playing, "player_queues/play_media", {"queue_id": "buero", "media": PIXEL})
    assert not _applied(playing, "player_queues/play_media", {"queue_id": "living", "media": IPHONE})
    assert _applied(playing, "players/cmd/set_members",
                    {"target_player": "buero", "player_ids_to_add": ["living"]})
    assert not _applied(playing, "players/cmd/set_members",
                        {"target_player": "buero", "player_ids_to_remove": ["living"]})
    assert not _applied(playing, "players/cmd/stop", {"player_id": "buero"})
