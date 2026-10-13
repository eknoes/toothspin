"""Minimal management web UI: pair phones, pair with Music Assistant, see status.

No authentication — it's meant for the home LAN only.
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any
from importlib.resources import files

from aiohttp import web
from dbus_fast.errors import DBusError

from . import speakers
from .bluez import BluetoothManager
from .ma import MusicAssistant, MusicAssistantError
from .receivers import Receivers

logger = logging.getLogger(__name__)


def create_app(
    bluetooth: BluetoothManager,
    receivers: Receivers,
    pairing_seconds: float,
    ma: MusicAssistant | None = None,
) -> web.Application:
    index = files(__package__).joinpath("index.html").read_text()

    async def get_index(_: web.Request) -> web.Response:
        return web.Response(text=index, content_type="text/html")

    def device_state(device: Any) -> dict[str, Any]:
        state = asdict(device)
        receiver = receivers.get(device.address)
        active = receiver.capture.active if receiver else None
        state["audio"] = (
            None
            if active is None
            else {
                "codec": active.codec,
                "now_playing": _asdict_or_none(bluetooth.now_playing(device.address)),
            }
        )
        state["sendspin"] = asdict(receiver.source.status()) if receiver else None
        state["source_uri"] = (
            speakers.source_uri(receiver.source.client.identity.peer_id) if receiver else None
        )
        return state

    async def get_state(_: web.Request) -> web.Response:
        remaining = bluetooth.pairing_remaining
        return web.json_response(
            {
                "bluetooth": {
                    "name": bluetooth.alias,
                    "address": bluetooth.address,
                    "pairing_remaining": None if remaining is None else round(remaining),
                },
                "devices": [device_state(d) for d in bluetooth.devices()],
                "speakers": None
                if ma is None
                else {
                    "connected": ma.connected,
                    "list": [
                        {**asdict(s), "can_group_with": sorted(s.can_group_with)}
                        for s in speakers.speakers(ma.players)
                    ],
                },
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

    async def post_sendspin_name(request: web.Request) -> web.Response:
        name = str((await request.json()).get("name", "")).strip()
        if not name or len(name) > 64:
            return web.json_response({"ok": False, "error": "Name must be 1-64 characters"}, status=400)
        try:
            await receivers.rename(request.match_info["address"], name)
        except KeyError:
            raise web.HTTPNotFound from None
        return web.json_response({"ok": True})

    async def post_speaker_toggle(request: web.Request) -> web.Response:
        receiver = receivers.get(request.match_info["address"])
        if receiver is None or ma is None:
            raise web.HTTPNotFound
        body = await request.json()
        uri = speakers.source_uri(receiver.source.client.identity.peer_id)
        try:
            await speakers.toggle(ma, uri, str(body["player_id"]), bool(body["on"]))
        except (MusicAssistantError, TimeoutError) as err:
            return web.json_response({"ok": False, "error": str(err)}, status=502)
        return web.json_response({"ok": True})

    async def post_sendspin_pairing(request: web.Request) -> web.Response:
        receiver = receivers.get(request.match_info["address"])
        if receiver is None:
            raise web.HTTPNotFound
        receiver.source.open_pairing_window()
        return web.json_response({"ok": True})

    app = web.Application()
    app.router.add_get("/", get_index)
    app.router.add_get("/api/state", get_state)
    app.router.add_post("/api/bluetooth/pairing", post_bt_pairing)
    app.router.add_post("/api/bluetooth/devices/{address}/{action}", post_bt_device)
    app.router.add_post("/api/sendspin/{address}/pairing", post_sendspin_pairing)
    app.router.add_post("/api/sendspin/{address}/name", post_sendspin_name)
    app.router.add_post("/api/speakers/{address}/toggle", post_speaker_toggle)
    return app


def _asdict_or_none(value: Any) -> dict[str, Any] | None:
    return None if value is None else asdict(value)
