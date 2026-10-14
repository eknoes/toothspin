import asyncio
from types import SimpleNamespace

import pytest
from aiosendspin.noise.pairing_token import decode_token

from toothspin.backend import BackendError
from toothspin.ma_pairing import pair


class FakeSource:
    def __init__(self) -> None:
        self.client = SimpleNamespace(identity=SimpleNamespace(
            peer_id="AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"))
        self.accepted = None

    async def accept_pairing(self, pairing) -> None:  # noqa: ANN001
        self.accepted = pairing


class FakeMA:
    """Music Assistant's "Pair the device" flow for a device that only offers tokens."""

    def __init__(self, steps: list[dict]) -> None:
        self.steps = steps
        self.calls: list[tuple[str, dict]] = []

    async def call(self, command: str, **args):  # noqa: ANN003
        self.calls.append((command, args))
        return self.steps.pop(0)


def test_answers_the_token_form_with_the_key_the_phone_accepted() -> None:
    source = FakeSource()
    ma = FakeMA([
        {"flow_id": "f1", "type": "form", "step_id": "enter_token"},
        {"flow_id": "f1", "type": "finish"},
    ])
    asyncio.run(pair(ma, source))  # type: ignore[arg-type]
    assert ma.calls[0] == ("config/players/setup", {"player_id": source.client.identity.peer_id})
    command, args = ma.calls[1]
    assert command == "config/flows/submit" and args["flow_id"] == "f1"
    token = decode_token(args["values"]["pairing_token"])
    assert token.client_id == source.client.identity.peer_id
    assert token.pairing_psk == source.accepted.psk


def test_a_failed_flow_is_aborted() -> None:
    source = FakeSource()
    ma = FakeMA([
        {"flow_id": "f2", "type": "form", "step_id": "enter_token"},
        {"flow_id": "f2", "type": "form", "step_id": "enter_token",
         "errors": {"base": "pairing_error_token_invalid"}},
        None,  # the abort
    ])
    with pytest.raises(BackendError, match="rejected"):
        asyncio.run(pair(ma, source))  # type: ignore[arg-type]
    assert ma.calls[-1] == ("config/flows/abort", {"flow_id": "f2"})
