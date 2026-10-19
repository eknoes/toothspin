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


def test_no_fill_for_toothspins_own_server(tmp_path) -> None:  # noqa: ANN001
    src = _source(tmp_path)
    src._fill_silence = False  # noqa: SLF001
    assert not src._wants_fill()  # noqa: SLF001


def test_no_fill_without_a_stream_request(tmp_path) -> None:
    src = _source(tmp_path)
    src._start_requested = False  # noqa: SLF001
    assert not src._wants_fill()  # noqa: SLF001


def test_quick_drops_back_off_and_warn_once(tmp_path, monkeypatch, caplog) -> None:
    import asyncio
    import logging

    src = SendspinSource("Pixel", "ws://127.0.0.1:1/sendspin", tmp_path)
    sleeps: list[float] = []

    class DroppingClient:
        """Like a server that drops us right away (a second client, same identity)."""

        async def connect(self, url: str) -> None:
            pass

        def add_disconnect_listener(self, callback):  # noqa: ANN001, ANN201
            callback()
            return lambda: None

    async def no_op(*_args) -> None:  # noqa: ANN002
        return None

    real_sleep = asyncio.sleep

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        if len(sleeps) >= 7:
            raise asyncio.CancelledError
        await real_sleep(0)

    src._client = DroppingClient()  # type: ignore[assignment]  # noqa: SLF001
    monkeypatch.setattr(src, "_signal_loop", no_op)
    monkeypatch.setattr(src, "_fill_loop", no_op)
    monkeypatch.setattr(src, "_reset", no_op)
    monkeypatch.setattr(src, "_refresh_paired", no_op)
    monkeypatch.setattr(src.client, "disconnect", no_op, raising=False)
    monkeypatch.setattr(source_module.asyncio, "sleep", sleep)
    caplog.set_level(logging.WARNING, logger="toothspin.source")
    try:
        asyncio.run(src.run())
    except asyncio.CancelledError:
        pass
    assert sleeps[:6] == [1.0, 2.0, 4.0, 8.0, 16.0, 32.0]
    assert sum("another ToothSpin" in r.getMessage() for r in caplog.records) == 1
