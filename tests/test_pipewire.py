from sendspin_bluetooth.pipewire import Source, parse_sources


def _node(props: dict) -> dict:
    return {"id": 1, "type": "PipeWire:Interface:Node", "info": {"props": props}}


def test_parse_sources_picks_bluetooth_capture_nodes() -> None:
    dump = [
        {"id": 0, "type": "PipeWire:Interface:Core", "info": {}},
        _node({"node.name": "Dummy-Driver"}),
        _node({"node.name": "alsa_input.mic", "media.class": "Audio/Source"}),
        _node({
            "node.name": "bluez_input.34_39_16_5D_41_B9.2",
            "node.description": "Pixel 10",
            "media.class": "Audio/Source",
            "api.bluez5.address": "34:39:16:5D:41:B9",
            "api.bluez5.codec": "aac",
        }),
    ]
    assert parse_sources(dump) == [
        Source("bluez_input.34_39_16_5D_41_B9.2", "Pixel 10", "34:39:16:5D:41:B9", "AAC")
    ]
