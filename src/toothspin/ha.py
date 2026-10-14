"""Running as a Home Assistant App (formerly add-on).

The Supervisor passes the user's settings as /data/options.json; they're
mapped onto the same environment variables the plain container uses, so
everything else stays identical. Ingress traffic must only be accepted from
the Supervisor's ingress proxy.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

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


async def ingress_port() -> int:
    """The port the Supervisor assigned for ingress (``ingress_port: 0``)."""
    api = os.environ.get("SUPERVISOR_API", "http://supervisor")
    headers = {"Authorization": f"Bearer {os.environ['SUPERVISOR_TOKEN']}"}
    async with (
        aiohttp.ClientSession() as session,
        session.get(f"{api}/addons/self/info", headers=headers) as response,
    ):
        response.raise_for_status()
        data = await response.json(content_type=None)
    return int(data["data"]["ingress_port"])
