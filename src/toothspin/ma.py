"""Minimal Music Assistant WebSocket API client: player list and a few commands.

Needs a long-lived MA token (MA_TOKEN). Player state is polled, which keeps
this independent of MA's event format.
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import logging
import re
from typing import Any

import aiohttp

from .backend import BackendError

logger = logging.getLogger(__name__)

POLL_S = 2.0
# Sendspin inputs arrived in 2.10.0, but PCM input (our default) and token
# pairing only work since 2.10.2. 2.10.6 is what ToothSpin is tested with.
MIN_VERSION = (2, 10, 2)


class MusicAssistantError(BackendError):
    pass


class MusicAssistant:
    def __init__(self, url: str | None, token: str) -> None:
        self._url = url.rstrip("/") + "/ws" if url else None
        self._token = token
        self._session: aiohttp.ClientSession | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._ids = itertools.count(1)
        self._pending: dict[str, asyncio.Future[Any]] = {}
        self._connected = asyncio.Event()
        self.players: list[dict[str, Any]] = []
        # Why there's no connection, for the web UI: "not_found", "auth" or
        # "unreachable"; None while connected or still trying the first time.
        self.problem: str | None = None
        # As Music Assistant reports it when connecting, e.g. "2.10.6".
        self.server_version: str | None = None

    @property
    def connected(self) -> bool:
        return self._connected.is_set()

    async def run(self) -> None:
        """Stay connected and keep ``players`` fresh."""
        self._session = aiohttp.ClientSession()
        try:
            backoff = 1.0
            while True:
                if self._url is None:
                    base_url = await discover_url()
                    if base_url is None:
                        self.problem = "not_found"
                        logger.warning("Music Assistant not found via mDNS; retrying in %.0fs", backoff)
                        await asyncio.sleep(backoff)
                        backoff = min(backoff * 2, 60.0)
                        continue
                    self._url = base_url.rstrip("/") + "/ws"
                try:
                    async with self._session.ws_connect(self._url, heartbeat=30) as ws:
                        self._ws = ws
                        info = await asyncio.wait_for(ws.receive_json(), 15)
                        self.server_version = info.get("server_version") or None
                        check_version(self.server_version)
                        reader = asyncio.create_task(self._read(ws))
                        try:
                            try:
                                await self._call("auth", token=self._token)
                            except MusicAssistantError:
                                self.problem = "auth"
                                raise
                            self.problem = None
                            self._connected.set()
                            backoff = 1.0
                            logger.info(
                                "Connected to Music Assistant %s API at %s",
                                self.server_version or "(unknown version)", self._url,
                            )
                            while not reader.done():
                                await self.refresh()
                                await asyncio.wait({reader}, timeout=POLL_S)
                        finally:
                            reader.cancel()
                            with contextlib.suppress(asyncio.CancelledError):
                                await reader
                except (OSError, aiohttp.ClientError, MusicAssistantError, TimeoutError) as err:
                    if self.problem != "auth":
                        self.problem = "unreachable"
                    logger.warning("Music Assistant API: %s; retrying in %.0fs", err, backoff)
                finally:
                    self._connected.clear()
                    self._ws = None
                    for future in self._pending.values():
                        future.cancel()
                    self._pending.clear()
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60.0)
        finally:
            await self._session.close()

    async def refresh(self) -> None:
        self.players = await self._call("players/all")

    async def call(self, command: str, **args: Any) -> Any:
        if not self.connected:
            raise MusicAssistantError("not connected to Music Assistant")
        return await self._call(command, **args)

    async def _call(self, command: str, **args: Any) -> Any:
        assert self._ws is not None
        message_id = str(next(self._ids))
        future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        self._pending[message_id] = future
        try:
            await self._ws.send_json({"message_id": message_id, "command": command, "args": args})
            return await asyncio.wait_for(future, 15)
        finally:
            self._pending.pop(message_id, None)

    async def _read(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        async for msg in ws:
            if msg.type is not aiohttp.WSMsgType.TEXT:
                continue
            data = msg.json()
            future = self._pending.get(str(data.get("message_id")))
            if future is None or future.done():
                continue  # events and stray replies
            if "error_code" in data:
                future.set_exception(
                    MusicAssistantError(data.get("details") or f"error {data['error_code']}")
                )
            else:
                future.set_result(data.get("result"))


def parse_version(version: str | None) -> tuple[int, int, int] | None:
    """(major, minor, patch) of e.g. "2.10.6", "2.11.0b5" or "2.11.0.dev2026101403"."""
    match = re.match(r"(\d+)\.(\d+)\.(\d+)", version or "")
    return tuple(int(part) for part in match.groups()) if match else None  # type: ignore[return-value]


def too_old(version: str | None) -> bool:
    parsed = parse_version(version)
    return parsed is not None and parsed < MIN_VERSION


def check_version(version: str | None) -> None:
    if too_old(version):
        logger.error(
            "Music Assistant %s is too old: ToothSpin needs %s or newer (2.10.6 or newer "
            "recommended). Update Music Assistant.", version, ".".join(map(str, MIN_VERSION)),
        )


async def probe_version(url: str | None) -> str | None:
    """Music Assistant's version without a token: its /info, or its mDNS announcement."""
    if url is None:
        found = await discover()
        return found[1] if found else None
    try:
        async with (
            aiohttp.ClientSession() as session,
            session.get(url.rstrip("/") + "/info", timeout=aiohttp.ClientTimeout(total=10)) as response,
        ):
            response.raise_for_status()
            return (await response.json(content_type=None)).get("server_version") or None
    except (aiohttp.ClientError, OSError, TimeoutError, ValueError):
        return None


async def discover_url(timeout: float = 3.0) -> str | None:
    """Music Assistant's base URL from its mDNS announcement (``_mass._tcp``)."""
    found = await discover(timeout)
    return found[0] if found else None


async def discover(timeout: float = 3.0) -> tuple[str, str | None] | None:
    """Music Assistant's base URL and version from its mDNS announcement (``_mass._tcp``).

    The announcement carries the same server info as the API, so this works
    without a token.
    """
    from zeroconf import ServiceStateChange
    from zeroconf.asyncio import AsyncServiceBrowser, AsyncServiceInfo, AsyncZeroconf

    service_type = "_mass._tcp.local."
    found: list[str] = []

    def on_change(zeroconf, service_type, name, state_change):  # noqa: ANN001
        if state_change is ServiceStateChange.Added:
            found.append(name)

    async with AsyncZeroconf() as azc:
        browser = AsyncServiceBrowser(azc.zeroconf, service_type, handlers=[on_change])
        await asyncio.sleep(timeout)
        await browser.async_cancel()
        for name in found:
            info = AsyncServiceInfo(service_type, name)
            if not await info.async_request(azc.zeroconf, 3000):
                continue
            version = (info.properties.get(b"server_version") or b"").decode() or None
            base_url = (info.properties.get(b"base_url") or b"").decode()
            if base_url:
                return base_url, version
            addresses = info.parsed_addresses()
            if addresses and info.port:
                return f"http://{addresses[0]}:{info.port}", version
    return None
