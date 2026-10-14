"""Pair a phone's input with Music Assistant through its API, no code to type.

Pairing the phone over Bluetooth is the user's consent; with a token for
Music Assistant's API, ToothSpin answers MA's "Pair the device" setup flow
itself. The phone's Sendspin source accepts a fresh pre-shared key, and MA
gets it as a pairing token, the method MA offers to devices without a PIN.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from aiosendspin.noise.keys import generate_psk, psk_id_for
from aiosendspin.noise.pairing_token import PSKPairingToken, encode_token
from aiosendspin.noise.trust_store import PairingPsk

from .backend import BackendError

if TYPE_CHECKING:
    from .ma import MusicAssistant
    from .source import SendspinSource

logger = logging.getLogger(__name__)

CHECK_S = 5.0
MAX_BACKOFF_S = 300.0
MAX_STEPS = 10


async def keep_paired(ma: MusicAssistant, source: SendspinSource) -> None:
    """Pair ``source`` with Music Assistant whenever it's connected but unpaired."""
    backoff = CHECK_S
    while True:
        await asyncio.sleep(backoff)
        status = source.status()
        client_id = source.client.identity.peer_id
        if not (ma.connected and status.connected) or status.paired:
            backoff = CHECK_S
            continue
        if not any(p.get("player_id") == client_id for p in ma.players):
            continue  # MA hasn't registered the input yet
        try:
            await pair(ma, source)
            logger.info("Paired %s with Music Assistant", status.name)
            backoff = CHECK_S
        except (BackendError, TimeoutError, KeyError) as err:
            backoff = min(backoff * 2, MAX_BACKOFF_S)
            logger.warning(
                "Pairing %s with Music Assistant failed: %s; retrying in %.0fs",
                status.name, err, backoff,
            )


async def remove(ma: MusicAssistant, client_id: str) -> None:
    """Remove a removed phone's input from Music Assistant too.

    MA only lets go of a device once it has said goodbye for good, which
    takes it a moment to process.
    """
    for _ in range(10):
        await asyncio.sleep(1.0)
        try:
            await ma.call("config/players/remove", player_id=client_id)
        except (BackendError, TimeoutError) as err:
            if "does not exist" in str(err):
                return
            last = err
            continue
        logger.info("Removed the input from Music Assistant")
        return
    logger.warning("Couldn't remove the input from Music Assistant: %s", last)


async def pair(ma: MusicAssistant, source: SendspinSource) -> None:
    client_id = source.client.identity.peer_id
    psk = generate_psk()
    await source.accept_pairing(PairingPsk(psk_id=psk_id_for(psk), psk=psk))
    token = encode_token(PSKPairingToken(client_id=client_id, pairing_psk=psk))
    step: dict[str, Any] = await ma.call("config/players/setup", player_id=client_id)
    try:
        for _ in range(MAX_STEPS):
            kind, step_id = step.get("type"), step.get("step_id")
            if kind == "finish":
                return
            if kind == "abort":
                raise BackendError(f"Music Assistant aborted pairing: {step.get('reason')}")
            if step.get("errors"):
                raise BackendError(f"Music Assistant rejected pairing: {step['errors']}")
            if kind == "progress":
                await asyncio.sleep(1.0)
                step = await ma.call("config/flows/get", flow_id=step["flow_id"])
            elif kind == "form" and step_id == "select_method":
                step = await ma.call(
                    "config/flows/submit", flow_id=step["flow_id"],
                    values={"pairing_method": "token"},
                )
            elif kind == "form" and step_id == "enter_token":
                step = await ma.call(
                    "config/flows/submit", flow_id=step["flow_id"],
                    values={"pairing_token": token},
                )
            else:
                raise BackendError(f"unexpected setup step {kind}/{step_id}")
        raise BackendError("Music Assistant's setup flow didn't finish")
    except BaseException:
        if step.get("type") not in ("finish", "abort"):
            try:
                await ma.call("config/flows/abort", flow_id=step["flow_id"])
            except (BackendError, TimeoutError):
                pass
        raise
