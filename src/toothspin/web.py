"""Minimal management web UI: pair phones, pair with Music Assistant, see status.

No authentication of its own: on the plain container it's meant for the home
LAN; as a Home Assistant App it sits behind HA's ingress, which only the
Supervisor's ingress proxy may reach.
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
from .ha import INGRESS_PROXY_IP
from .backend import BackendError, PlayerBackend
from .receivers import Receivers

logger = logging.getLogger(__name__)


def create_app(
    bluetooth: BluetoothManager,
    receivers: Receivers,
    pairing_seconds: float,
    backend: PlayerBackend | None = None,
    ingress_port: int | None = None,
    start_volume: int = 100,
    auto_pairing: bool = False,
) -> web.Application:
    index = files(__package__).joinpath("index.html").read_text()
    volumes = speakers.Volumes(backend) if backend else None

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
        state["hidden_speakers"] = receivers.hidden_speakers(device.address) if receiver else []
        state["source_uri"] = (
            speakers.source_uri(receiver.source.client.identity.peer_id) if receiver else None
        )
        return state

    async def get_state(_: web.Request) -> web.Response:
        remaining = bluetooth.pairing_remaining
        return web.json_response(
            {
                "auto_pairing": auto_pairing,
                "bluetooth": {
                    "name": bluetooth.alias,
                    "address": bluetooth.address,
                    "pairing_remaining": None if remaining is None else round(remaining),
                },
                "devices": [device_state(d) for d in bluetooth.devices()],
                "speakers": None
                if backend is None
                else {
                    "connected": backend.connected,
                    "list": [
                        {**asdict(s), "can_group_with": sorted(s.can_group_with)}
                        for s in speakers.speakers(backend.players, volumes.emulated_mutes)
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
                await receivers.forget(address)
            elif action == "connect":
                await bluetooth.connect_device(address)
            elif action == "disconnect":
                await bluetooth.disconnect_device(address)
            else:
                raise web.HTTPNotFound
        except KeyError:
            raise web.HTTPNotFound from None
        except (DBusError, TimeoutError) as err:
            return web.json_response(
                {"ok": False, "error": f"{action.title()} failed: {err or 'timed out'}"}, status=502
            )
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
        if receiver is None or backend is None:
            raise web.HTTPNotFound
        body = await request.json()
        uri = speakers.source_uri(receiver.source.client.identity.peer_id)
        try:
            await speakers.toggle(backend, uri, str(body["player_id"]), bool(body["on"]), start_volume)
        except (BackendError, TimeoutError) as err:
            return web.json_response({"ok": False, "error": str(err)}, status=502)
        return web.json_response({"ok": True})

    async def post_speaker_move(request: web.Request) -> web.Response:
        receiver = receivers.get(request.match_info["address"])
        if receiver is None or backend is None:
            raise web.HTTPNotFound
        body = await request.json()
        uri = speakers.source_uri(receiver.source.client.identity.peer_id)
        try:
            await speakers.move(backend, uri, str(body["player_id"]), start_volume)
        except (BackendError, TimeoutError) as err:
            return web.json_response({"ok": False, "error": str(err)}, status=502)
        return web.json_response({"ok": True})

    async def post_speaker_hidden(request: web.Request) -> web.Response:
        body = await request.json()
        try:
            receivers.set_speaker_hidden(
                request.match_info["address"], str(body["player_id"]), bool(body["hidden"])
            )
        except KeyError:
            raise web.HTTPNotFound from None
        return web.json_response({"ok": True})

    async def post_speaker_volume(request: web.Request) -> web.Response:
        if volumes is None:
            raise web.HTTPNotFound
        body = await request.json()
        try:
            if "muted" in body:
                await volumes.set_muted(str(body["player_id"]), bool(body["muted"]))
            else:
                await volumes.set_volume(str(body["player_id"]), int(body["volume"]))
        except (BackendError, TimeoutError) as err:
            return web.json_response({"ok": False, "error": str(err)}, status=502)
        return web.json_response({"ok": True})

    async def post_sendspin_pairing(request: web.Request) -> web.Response:
        receiver = receivers.get(request.match_info["address"])
        if receiver is None:
            raise web.HTTPNotFound
        receiver.source.open_pairing_window()
        return web.json_response({"ok": True})

    @web.middleware
    async def ingress_only(request: web.Request, handler: Any) -> web.StreamResponse:
        # HA ingress handles authentication; the ingress port must therefore
        # only answer the Supervisor's proxy, not anyone on the network.
        sockname = request.transport.get_extra_info("sockname") if request.transport else None
        if sockname and sockname[1] == ingress_port and request.remote != INGRESS_PROXY_IP:
            raise web.HTTPForbidden(text="Use Home Assistant to open ToothSpin.")
        return await handler(request)

    app = web.Application(middlewares=[ingress_only] if ingress_port else [])
    app.router.add_get("/", get_index)
    static = files(__package__).joinpath("static")
    app.router.add_static("/static/", str(static))

    async def get_sw(_: web.Request) -> web.Response:
        # Served from the root so its scope covers the whole app.
        return web.Response(
            text=static.joinpath("sw.js").read_text(), content_type="application/javascript"
        )

    app.router.add_get("/sw.js", get_sw)
    app.router.add_get("/api/state", get_state)
    app.router.add_post("/api/bluetooth/pairing", post_bt_pairing)
    app.router.add_post("/api/bluetooth/devices/{address}/{action}", post_bt_device)
    app.router.add_post("/api/sendspin/{address}/pairing", post_sendspin_pairing)
    app.router.add_post("/api/sendspin/{address}/name", post_sendspin_name)
    app.router.add_post("/api/speakers/{address}/toggle", post_speaker_toggle)
    app.router.add_post("/api/speakers/{address}/move", post_speaker_move)
    app.router.add_post("/api/speakers/volume", post_speaker_volume)
    app.router.add_post("/api/speakers/{address}/hidden", post_speaker_hidden)
    return app


def _asdict_or_none(value: Any) -> dict[str, Any] | None:
    return None if value is None else asdict(value)
