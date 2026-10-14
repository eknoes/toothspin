"""Minimal management web UI: pair phones, pair with Music Assistant, see status.

No authentication of its own: on the plain container it's meant for the home
LAN; as a Home Assistant App it sits behind HA's ingress, which only the
Supervisor's ingress proxy may reach.
"""

from __future__ import annotations

import asyncio
import itertools
import logging
from dataclasses import asdict
from typing import Any
from importlib.resources import files

import aiohttp
from aiohttp import web
from dbus_fast.errors import DBusError

from . import ha, ma, setup_check, speakers
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
    status: setup_check.Status | None = None,
) -> web.Application:
    volumes = speakers.Volumes(backend) if backend else None

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
        state["reconnecting"] = bluetooth.reconnecting(device.address)
        state["source_uri"] = (
            speakers.source_uri(receiver.source.client.identity.peer_id) if receiver else None
        )
        return state

    async def get_state(_: web.Request) -> web.Response:
        remaining = bluetooth.pairing_remaining
        return web.json_response(
            {
                "auto_pairing": auto_pairing,
                "setup": _setup_state(status, backend, bluetooth) if status else None,
                "bluetooth": {
                    "name": bluetooth.alias,
                    "address": bluetooth.address,
                    "pairing_remaining": None if remaining is None else round(remaining),
                    "pin_pairing": bluetooth.pin_pairing,
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

    # Quick clicks on several speakers arrive nearly at once; each plans from
    # the grouping the one before left, not all from the same old one.
    routing = asyncio.Lock()
    tickets = itertools.count()
    latest: dict[tuple[str, str], int] = {}

    async def post_speaker_toggle(request: web.Request) -> web.Response:
        receiver = receivers.get(request.match_info["address"])
        if receiver is None or backend is None:
            raise web.HTTPNotFound
        body = await request.json()
        uri = speakers.source_uri(receiver.source.client.identity.peer_id)
        player_id = str(body["player_id"])
        # Only the latest click on a speaker matters: one still waiting
        # behind a slow request is skipped once a newer one arrives.
        key = (uri, player_id)
        ticket = latest[key] = next(tickets)
        try:
            async with routing:
                if latest[key] != ticket:
                    return web.json_response({"ok": True, "superseded": True})
                await speakers.toggle(backend, uri, player_id, bool(body["on"]), start_volume)
        except (BackendError, TimeoutError) as err:
            return _backend_error(err)
        return web.json_response({"ok": True})

    async def post_speaker_move(request: web.Request) -> web.Response:
        receiver = receivers.get(request.match_info["address"])
        if receiver is None or backend is None:
            raise web.HTTPNotFound
        body = await request.json()
        uri = speakers.source_uri(receiver.source.client.identity.peer_id)
        try:
            async with routing:
                await speakers.move(backend, uri, str(body["player_id"]), start_volume)
        except (BackendError, TimeoutError) as err:
            return _backend_error(err)
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
            return _backend_error(err)
        return web.json_response({"ok": True})

    async def post_sendspin_pairing(request: web.Request) -> web.Response:
        receiver = receivers.get(request.match_info["address"])
        if receiver is None:
            raise web.HTTPNotFound
        receiver.source.open_pairing_window()
        return web.json_response({"ok": True})

    async def post_setup_ignore_adapter(_: web.Request) -> web.Response:
        # The "Ignore" Home Assistant offers for a discovered adapter, done for
        # the user on their click.
        if status is None or status.adapter is None or not status.app:
            raise web.HTTPNotFound
        try:
            ignored = await ha.ignore_discovered(status.adapter.address)
        except (aiohttp.ClientError, OSError, RuntimeError, TimeoutError) as err:
            return web.json_response(
                {"ok": False, "error": f"Home Assistant: {err}"}, status=502
            )
        if status.warning is not None and status.warning.action == "ignore-adapter":
            status.warning = None
        if not ignored:
            return web.json_response(
                {"ok": False, "error": "Home Assistant no longer offers that adapter."},
                status=409,
            )
        return web.json_response({"ok": True})

    app = _base_app(ingress_port)
    app.router.add_get("/api/state", get_state)
    app.router.add_post("/api/setup/ignore-adapter", post_setup_ignore_adapter)
    app.router.add_post("/api/bluetooth/pairing", post_bt_pairing)
    app.router.add_post("/api/bluetooth/devices/{address}/{action}", post_bt_device)
    app.router.add_post("/api/sendspin/{address}/pairing", post_sendspin_pairing)
    app.router.add_post("/api/sendspin/{address}/name", post_sendspin_name)
    app.router.add_post("/api/speakers/{address}/toggle", post_speaker_toggle)
    app.router.add_post("/api/speakers/{address}/move", post_speaker_move)
    app.router.add_post("/api/speakers/volume", post_speaker_volume)
    app.router.add_post("/api/speakers/{address}/hidden", post_speaker_hidden)
    return app


def create_setup_app(status: setup_check.Status, ingress_port: int | None) -> web.Application:
    """Before Bluetooth starts: only explains what blocks ToothSpin."""

    async def get_state(_: web.Request) -> web.Response:
        return web.json_response({"setup": _setup_state(status, None, None)})

    app = _base_app(ingress_port)
    app.router.add_get("/api/state", get_state)
    return app


def _base_app(ingress_port: int | None) -> web.Application:
    """The page, its static files and, behind ingress, the proxy-only guard."""
    index = files(__package__).joinpath("index.html").read_text()
    static = files(__package__).joinpath("static")

    @web.middleware
    async def ingress_only(request: web.Request, handler: Any) -> web.StreamResponse:
        # HA ingress handles authentication; the ingress port must therefore
        # only answer the Supervisor's proxy, not anyone on the network.
        sockname = request.transport.get_extra_info("sockname") if request.transport else None
        if sockname and sockname[1] == ingress_port and request.remote != INGRESS_PROXY_IP:
            raise web.HTTPForbidden(text="Use Home Assistant to open ToothSpin.")
        return await handler(request)

    async def get_index(_: web.Request) -> web.Response:
        return web.Response(text=index, content_type="text/html")

    async def get_sw(_: web.Request) -> web.Response:
        # Served from the root so its scope covers the whole app.
        return web.Response(
            text=static.joinpath("sw.js").read_text(), content_type="application/javascript"
        )

    app = web.Application(middlewares=[ingress_only] if ingress_port else [])
    app.router.add_get("/", get_index)
    app.router.add_static("/static/", str(static))
    app.router.add_get("/sw.js", get_sw)
    return app


def _backend_error(err: Exception) -> web.Response:
    # A timeout has no message of its own.
    message = str(err) or (
        "Music Assistant didn't answer in time. Try again in a moment."
        if isinstance(err, TimeoutError) else type(err).__name__
    )
    return web.json_response({"ok": False, "error": message}, status=502)


def _problem(problem: setup_check.Problem | None) -> dict[str, Any] | None:
    if problem is None:
        return None
    return {
        "title": problem.title, "text": problem.text, "steps": problem.steps,
        "action": problem.action,
    }


def _setup_state(
    status: setup_check.Status,
    backend: PlayerBackend | None,
    bluetooth: BluetoothManager | None,
) -> dict[str, Any]:
    """A blocking problem, or what's left to finish setup.

    ``todo`` only holds what still needs the user (or is on its way):
    finished steps drop out, and once it's empty the web UI shows nothing.
    """
    todo: list[dict[str, Any]] = []
    version = getattr(backend, "server_version", None) or status.ma_version
    if ma.too_old(version):
        todo.append({
            "kind": "todo",
            "title": "Update Music Assistant",
            "text": f"This Music Assistant is version {version}. ToothSpin needs "
            f"{'.'.join(map(str, ma.MIN_VERSION))} or newer (2.10.6 or newer recommended): "
            "older versions can't play phones' audio or pair them.",
            "steps": [
                "Update Music Assistant. In Home Assistant: **Settings → Apps → Music "
                "Assistant → Update**.",
            ],
        })
    if status.warning is not None:
        todo.append(_problem(status.warning) | {"kind": "todo"})
    if not status.ma_token:
        todo.append({
            "kind": "todo",
            "title": "Add a Music Assistant token",
            "text": "To pick speakers here, pair phones with Music Assistant by "
            "themselves, and control the speakers with the phone's volume buttons.",
            "steps": [
                "In Music Assistant, click your profile (bottom left) → **Tokens** → "
                "**Create token**, and copy it.",
                (
                    "Paste it as **Music Assistant token** in [ToothSpin's "
                    "configuration](ha:app-config), save and restart ToothSpin."
                    if status.app else
                    "Set it as `MA_TOKEN` (e.g. in `~/.config/toothspin.env`) and restart "
                    "ToothSpin."
                ),
            ],
        })
    elif backend is not None and not backend.connected:
        problem = getattr(backend, "problem", None)
        title, text, steps = {
            "auth": (
                "Replace the Music Assistant token",
                "Music Assistant rejected the token.",
                ["Create a new token in Music Assistant (profile → **Tokens**) and "
                 "replace the one in [ToothSpin's configuration](ha:app-config), then "
                 "restart ToothSpin."],
            ),
            "not_found": (
                "Music Assistant not found",
                "ToothSpin couldn't find Music Assistant on the network.",
                ["Make sure Music Assistant (2.10.6 or newer) is installed and running.",
                 "If it runs elsewhere, set **Music Assistant URL** in [ToothSpin's "
                 "configuration](ha:app-config), e.g. `http://192.168.1.10:8095`."],
            ),
            "unreachable": (
                "Music Assistant unreachable",
                "Music Assistant can't be reached right now; ToothSpin keeps retrying.",
                ["Check that Music Assistant is running."],
            ),
        }.get(problem or "", ("Connecting to Music Assistant…", "", []))
        todo.append({"kind": "wait" if problem is None else "todo",
                     "title": title, "text": text, "steps": steps})
    if bluetooth is not None and not bluetooth.devices():
        todo.append({
            "kind": "hint",
            "title": "Pair your first phone",
            "text": f"Press **Add phone** below, then connect to “{bluetooth.alias}” "
            "in the phone's Bluetooth settings.",
            "steps": [],
        })
    return {
        "problem": _problem(status.problem),
        "todo": todo,
        "app": status.app,
        "app_slug": status.app_slug,
    }


def _asdict_or_none(value: Any) -> dict[str, Any] | None:
    return None if value is None else asdict(value)
