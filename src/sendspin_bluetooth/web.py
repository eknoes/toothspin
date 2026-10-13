"""Minimal management web UI: pair phones, pair with Music Assistant, see status.

No authentication — it's meant for the home LAN only.
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from importlib.resources import files

from aiohttp import web
from dbus_fast.errors import DBusError

from .bluez import BluetoothManager
from .capture import Capture
from .source import SendspinSource

logger = logging.getLogger(__name__)


def create_app(
    bluetooth: BluetoothManager,
    source: SendspinSource,
    capture: Capture,
    pairing_seconds: float,
) -> web.Application:
    index = files(__package__).joinpath("index.html").read_text()

    async def get_index(_: web.Request) -> web.Response:
        return web.Response(text=index, content_type="text/html")

    async def get_state(_: web.Request) -> web.Response:
        active = capture.active
        remaining = bluetooth.pairing_remaining
        return web.json_response(
            {
                "bluetooth": {
                    "name": bluetooth.alias,
                    "address": bluetooth.address,
                    "pairing_remaining": None if remaining is None else round(remaining),
                    "devices": [asdict(d) for d in bluetooth.devices()],
                },
                "audio": None
                if active is None
                else {"device": active.description, "codec": active.codec},
                "sendspin": asdict(source.status()),
            }
        )

    async def post_bt_pairing(request: web.Request) -> web.Response:
        body = await request.json()
        if body.get("open"):
            await bluetooth.open_pairing(pairing_seconds)
        else:
            await bluetooth.close_pairing()
        return web.json_response({"ok": True})

    async def post_bt_device(request: web.Request) -> web.Response:
        address = request.match_info["address"]
        action = request.match_info["action"]
        try:
            if action == "remove":
                await bluetooth.remove_device(address)
            elif action == "disconnect":
                await bluetooth.disconnect_device(address)
            else:
                raise web.HTTPNotFound
        except KeyError:
            raise web.HTTPNotFound from None
        except DBusError as err:
            return web.json_response({"ok": False, "error": str(err)}, status=502)
        return web.json_response({"ok": True})

    async def post_sendspin_pairing(_: web.Request) -> web.Response:
        source.open_pairing_window()
        return web.json_response({"ok": True})

    app = web.Application()
    app.router.add_get("/", get_index)
    app.router.add_get("/api/state", get_state)
    app.router.add_post("/api/bluetooth/pairing", post_bt_pairing)
    app.router.add_post("/api/bluetooth/devices/{address}/{action}", post_bt_device)
    app.router.add_post("/api/sendspin/pairing", post_sendspin_pairing)
    return app
