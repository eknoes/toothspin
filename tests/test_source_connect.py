import asyncio
import logging

from aiosendspin.models.types import ServerErrorReason
from aiosendspin.noise import HandshakeAbortedError, InitRejectedError

from toothspin import source as source_module
from toothspin.source import SendspinSource


def _run(src: SendspinSource, monkeypatch, errors: list[Exception]) -> list[bool]:  # noqa: ANN001
    """Connect once per error (each raised by the handshake), then once fine;
    the source's ``incompatible`` after each attempt."""
    seen: list[bool] = []

    class Client:
        async def connect(self, url: str) -> None:
            if errors:
                raise errors.pop(0)

        def add_disconnect_listener(self, callback):  # noqa: ANN001, ANN201
            callback()
            return lambda: None

    async def no_op(*_args) -> None:  # noqa: ANN002
        return None

    async def sleep(_seconds: float) -> None:
        seen.append(src._incompatible)  # noqa: SLF001
        if not errors and len(seen) > 1 and not seen[-1]:
            raise asyncio.CancelledError

    src._client = Client()  # type: ignore[assignment]  # noqa: SLF001
    for name in ("_signal_loop", "_fill_loop", "_reset", "_refresh_paired"):
        monkeypatch.setattr(src, name, no_op)
    monkeypatch.setattr(src.client, "disconnect", no_op, raising=False)
    monkeypatch.setattr(source_module.asyncio, "sleep", sleep)
    try:
        asyncio.run(src.run())
    except asyncio.CancelledError:
        pass
    return seen


def test_another_sendspin_version_is_reported_and_retried(tmp_path, monkeypatch, caplog) -> None:
    src = SendspinSource("Pixel", "ws://127.0.0.1:1/sendspin", tmp_path)
    caplog.set_level(logging.WARNING, logger="toothspin.source")
    # An older server (Music Assistant 2.10.6), then a newer one, then it's updated.
    old = HandshakeAbortedError("malformed Noise message 1 payload: psk_category missing")
    new = InitRejectedError(ServerErrorReason.UNSUPPORTED_VERSION, "unsupported protocol version 2")
    assert _run(src, monkeypatch, [old, old, new]) == [True, True, True, False]
    assert sum("needs an update" in r.getMessage() for r in caplog.records) == 1


def test_other_handshake_failures_are_no_version_problem(tmp_path, monkeypatch) -> None:
    src = SendspinSource("Pixel", "ws://127.0.0.1:1/sendspin", tmp_path)
    errors: list[Exception] = [HandshakeAbortedError("timed out awaiting noise message 2")]
    assert _run(src, monkeypatch, errors) == [False, False]
