"""Running as a Home Assistant App (formerly add-on).

The Supervisor passes the user's settings as /data/options.json; they're
mapped onto the same environment variables the plain container uses, so
everything else stays identical. Ingress traffic must only be accepted from
the Supervisor's ingress proxy.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)

OPTIONS_PATH = Path("/data/options.json")
# Source address of the Supervisor's ingress proxy; only it may reach the
# ingress port (https://developers.home-assistant.io/docs/apps/presentation).
INGRESS_PROXY_IP = "172.30.32.2"

# App option -> environment variable read by the service.
OPTION_ENV = {
    "bluetooth_name": "BT_NAME",
    "input_name": "SENDSPIN_NAME",
    "adapter": "BT_ADAPTER",
    "start_volume": "START_VOLUME",
    "allow_phone_connect": "ALLOW_PHONE_CONNECT",
    "sendspin_url": "SENDSPIN_URL",
    "ma_url": "MA_URL",
    "ma_token": "MA_TOKEN",
    "lan_port": "LAN_PORT",
    "log_level": "LOG_LEVEL",
}


def running_as_app() -> bool:
    return "SUPERVISOR_TOKEN" in os.environ


def apply_options(path: Path = OPTIONS_PATH) -> bool:
    """Export the App's options as environment defaults; False outside HA."""
    if not path.exists():
        return False
    options = json.loads(path.read_text())
    for key, env in OPTION_ENV.items():
        value = options.get(key)
        if value is None or value == "":
            continue
        os.environ.setdefault(env, str(value).upper() if key == "log_level" else str(value))
    return True


async def app_info() -> tuple[int, str]:
    """The ingress port the Supervisor assigned (``ingress_port: 0``) and our
    slug, which Home Assistant's pages for the App are named after."""
    api = os.environ.get("SUPERVISOR_API", "http://supervisor")
    headers = {"Authorization": f"Bearer {os.environ['SUPERVISOR_TOKEN']}"}
    async with (
        aiohttp.ClientSession() as session,
        session.get(f"{api}/addons/self/info", headers=headers) as response,
    ):
        response.raise_for_status()
        data = await response.json(content_type=None)
    return int(data["data"]["ingress_port"]), str(data["data"]["slug"])


SIDEBAR_MARKER = Path("/data/.sidebar_shown")


async def show_in_sidebar(marker: Path = SIDEBAR_MARKER) -> None:
    """Put ToothSpin in Home Assistant's sidebar, once.

    Same as the App page's "Show in sidebar" switch, which is off for new
    installs. Only done on the first start, so switching it off sticks.
    """
    if marker.exists():
        return
    headers = {"Authorization": f"Bearer {os.environ['SUPERVISOR_TOKEN']}"}
    async with (
        aiohttp.ClientSession() as session,
        session.post(
            f"{_api()}/addons/self/options", headers=headers, json={"ingress_panel": True}
        ) as response,
    ):
        response.raise_for_status()
    marker.touch()
    logger.info("Added ToothSpin to Home Assistant's sidebar")


# How Home Assistant's Bluetooth integration treats an adapter, by address.
USED = "used"  # set up and enabled: HA scans with it
DISABLED = "disabled"  # set up, but disabled by the user: free for ToothSpin
IGNORED = "ignored"  # discovered, and the user chose to ignore it
OFFERED = "offered"  # discovered, waiting to be added: one click from USED

_ADDRESS = re.compile(r"\(([0-9A-F]{2}(?::[0-9A-F]{2}){5})\)", re.IGNORECASE)


async def bluetooth_adapter_usage() -> dict[str, str]:
    """What Home Assistant's Bluetooth integration does with each adapter.

    Its config entries are titled "<manufacturer> <model> (<address>)", one
    per adapter; adapters it discovered but nobody added yet show up as
    flows in progress, keyed by the same address.
    """
    entries, flows = await _websocket(
        {"type": "config_entries/get", "domain": "bluetooth"},
        {"type": "config_entries/flow/progress"},
    )
    usage: dict[str, str] = {}
    for flow in flows or []:
        address = (flow.get("context") or {}).get("unique_id")
        if flow.get("handler") == "bluetooth" and address:
            usage[address.upper()] = OFFERED
    for entry in entries or []:
        match = _ADDRESS.search(entry.get("title") or "")
        if not match:
            continue
        if entry.get("source") == "ignore":
            state = IGNORED
        elif entry.get("disabled_by"):
            state = DISABLED
        else:
            state = USED
        usage[match.group(1).upper()] = state
    return usage


async def ignore_discovered(address: str) -> bool:
    """Ignore Home Assistant's offer to add the adapter, like its Ignore button.

    The title keeps the address, which is how bluetooth_adapter_usage()
    recognises the ignored entry. False if there was no such offer.
    """
    (flows,) = await _websocket({"type": "config_entries/flow/progress"})
    flow = next(
        (
            f for f in flows or []
            if f.get("handler") == "bluetooth"
            and str((f.get("context") or {}).get("unique_id", "")).upper() == address.upper()
        ),
        None,
    )
    if flow is None:
        return False
    await _websocket({
        "type": "config_entries/ignore_flow",
        "flow_id": flow["flow_id"],
        "title": f"ToothSpin ({address.upper()})",
    })
    return True


async def notify(notification_id: str, title: str, message: str) -> None:
    """A notification in Home Assistant's notification panel."""
    await _service(
        "persistent_notification", "create",
        {"notification_id": notification_id, "title": title, "message": message},
    )


async def dismiss(notification_id: str) -> None:
    await _service("persistent_notification", "dismiss", {"notification_id": notification_id})


def _api() -> str:
    return os.environ.get("SUPERVISOR_API", "http://supervisor")


async def _service(domain: str, service: str, data: dict[str, Any]) -> None:
    headers = {"Authorization": f"Bearer {os.environ['SUPERVISOR_TOKEN']}"}
    async with (
        aiohttp.ClientSession() as session,
        session.post(
            f"{_api()}/core/api/services/{domain}/{service}", json=data, headers=headers
        ) as response,
    ):
        response.raise_for_status()


async def _websocket(*commands: dict[str, Any]) -> list[Any]:
    """Run commands over Home Assistant's WebSocket API (via the Supervisor)."""
    url = _api().replace("http", "ws", 1) + "/core/websocket"
    results: list[Any] = []
    async with aiohttp.ClientSession() as session, session.ws_connect(url) as ws:
        await asyncio.wait_for(ws.receive_json(), 10)  # auth_required
        await ws.send_json({"type": "auth", "access_token": os.environ["SUPERVISOR_TOKEN"]})
        reply = await asyncio.wait_for(ws.receive_json(), 10)
        if reply.get("type") != "auth_ok":
            raise RuntimeError(f"Home Assistant refused the connection: {reply}")
        for number, command in enumerate(commands, start=1):
            await ws.send_json({"id": number, **command})
            while True:
                reply = await asyncio.wait_for(ws.receive_json(), 10)
                if reply.get("id") == number and reply.get("type") == "result":
                    break
            if not reply.get("success"):
                raise RuntimeError(f"{command['type']} failed: {reply.get('error')}")
            results.append(reply.get("result"))
    return results
