import time
from types import SimpleNamespace

from toothspin import source as source_module
from toothspin.source import SendspinSource


def _source(tmp_path) -> SendspinSource:  # noqa: ANN001
    src = SendspinSource("Pixel", "ws://127.0.0.1:1/sendspin", tmp_path)
    src._client = SimpleNamespace(connected=True)  # type: ignore[assignment]  # noqa: SLF001
    src._start_requested = True  # noqa: SLF001
    src._started_at = time.monotonic()  # noqa: SLF001
    return src


def test_fills_until_the_phone_plays_and_while_it_pauses(tmp_path, monkeypatch) -> None:
    src = _source(tmp_path)
    assert src._wants_fill()  # noqa: SLF001 - not playing yet
    src._audio_since_start = True  # noqa: SLF001
    src._last_audio = time.monotonic()  # noqa: SLF001
    assert not src._wants_fill()  # noqa: SLF001 - playing
    src._last_audio -= 5  # noqa: SLF001
    assert src._wants_fill()  # noqa: SLF001 - paused: keep the speakers
    src._last_audio -= source_module.PAUSE_FILL_S  # noqa: SLF001
    assert not src._wants_fill()  # noqa: SLF001 - paused too long: let them go


def test_no_fill_without_a_stream_request(tmp_path) -> None:
    src = _source(tmp_path)
    src._start_requested = False  # noqa: SLF001
    assert not src._wants_fill()  # noqa: SLF001
