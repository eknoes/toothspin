"""Album covers from the phones, for speakers with a display and the web UI.

Phones offer the current track's cover over AVRCP's cover art protocol (BIP
over OBEX). BlueZ's obexd fetches it: ToothSpin runs its own, client part
only (it offers phones nothing), on a private D-Bus of its own. BlueZ only
includes a track's image handle while a cover art session to the phone is
open, so one stays open per connected phone that offers covers.

It needs no privileges: obexd's Bluetooth socket (L2CAP) works from a
rootless container too. Without obexd (outside the image) there are no
covers; everything else works the same.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from dbus_fast import Variant
from dbus_fast.aio import MessageBus
from dbus_fast.errors import DBusError

from . import dbus

if TYPE_CHECKING:
    from .bluez import BluetoothDevice, NowPlaying

logger = logging.getLogger(__name__)

OBEXD = "/usr/lib/bluetooth/obexd"
OBEX = "org.bluez.obex"
OBEX_PATH = "/org/bluez/obex"
# How often to look for new tracks, and how long to wait after a failure.
POLL_S = 1.0
RETRY_S = 30.0
FETCH_TIMEOUT_S = 15.0
# Covers kept per phone: tracks come round again.
CACHE = 8
# A bus for obexd and ToothSpin only: no service activation, so nothing can
# start an obexd that offers phones file transfer.
_BUS_CONFIG = """<!DOCTYPE busconfig PUBLIC "-//freedesktop//DTD D-BUS Bus Configuration 1.0//EN"
 "http://www.freedesktop.org/standards/dbus/1.0/busconfig.dtd">
<busconfig>
  <type>session</type>
  <listen>{address}</listen>
  <auth>EXTERNAL</auth>
  <policy context="default">
    <allow send_destination="*"/>
    <allow own="*"/>
  </policy>
</busconfig>
"""


class Phones(Protocol):
    """What covers need to know about the phones (``BluetoothManager``)."""

    def devices(self) -> list[BluetoothDevice]: ...

    def cover_port(self, address: str) -> int | None: ...

    def now_playing(self, address: str) -> NowPlaying | None: ...


class Obex(Protocol):
    async def open(self, address: str, port: int) -> str:
        """Open a cover art session to a phone; returns its path."""

    async def close(self, session: str) -> None: ...

    async def fetch(self, session: str, handle: str) -> bytes:
        """The cover with this image handle (a JPEG thumbnail, 200x200)."""


@dataclass
class _Phone:
    session: str | None = None
    retry_at: float = 0.0
    covers: OrderedDict[str, bytes] = field(default_factory=OrderedDict)
    """By image handle, most recent last."""
    warned: bool = False


class Covers:
    """Keeps the current track's cover of every connected phone."""

    def __init__(self, phones: Phones, obex: Obex) -> None:
        self._phones = phones
        self._obex = obex
        self._state: dict[str, _Phone] = {}

    def cover(self, address: str) -> tuple[str, bytes] | None:
        """The phone's current cover as (image handle, JPEG), once fetched."""
        state = self._state.get(address.upper())
        playing = self._phones.now_playing(address)
        handle = playing.image_handle if playing else None
        if state is None or handle is None or handle not in state.covers:
            return None
        return handle, state.covers[handle]

    async def run(self) -> None:
        while True:
            try:
                await self.sync()
            except Exception:
                logger.exception("Fetching covers failed")
            await asyncio.sleep(POLL_S)

    async def sync(self) -> None:
        """Open and close sessions as phones come and go; fetch new covers."""
        connected = {d.address.upper() for d in self._phones.devices() if d.connected}
        for address in [a for a in self._state if a not in connected]:
            await self._close(self._state.pop(address))
        for address in connected:
            port = self._phones.cover_port(address)
            if port is None:
                continue
            state = self._state.setdefault(address, _Phone())
            if state.session is None and not await self._open(address, port, state):
                continue
            playing = self._phones.now_playing(address)
            handle = playing.image_handle if playing else None
            if handle is None or handle in state.covers:
                continue
            assert state.session is not None
            try:
                async with asyncio.timeout(FETCH_TIMEOUT_S):
                    cover = await self._obex.fetch(state.session, handle)
            except (DBusError, OSError, TimeoutError) as err:
                self._failed(address, state, f"fetching a cover failed: {err or 'timed out'}")
                await self._close(state)
                continue
            state.covers[handle] = cover
            while len(state.covers) > CACHE:
                state.covers.popitem(last=False)

    async def _open(self, address: str, port: int, state: _Phone) -> bool:
        if time.monotonic() < state.retry_at:
            return False
        try:
            state.session = await self._obex.open(address, port)
        except (DBusError, OSError, TimeoutError) as err:
            self._failed(address, state, f"no cover art session: {err or 'timed out'}")
            return False
        # Image handles only hold within a session.
        state.covers.clear()
        return True

    def _failed(self, address: str, state: _Phone, message: str) -> None:
        state.retry_at = time.monotonic() + RETRY_S
        # Once per phone at warning level; it keeps trying.
        if not state.warned:
            logger.warning("Covers from %s: %s", address, message)
            state.warned = True
        else:
            logger.debug("Covers from %s: %s", address, message)

    async def _close(self, state: _Phone) -> None:
        if state.session is not None:
            # Gone with the phone's connection already, usually.
            with contextlib.suppress(DBusError, OSError):
                await self._obex.close(state.session)
            state.session = None


class ObexDaemon:
    """obexd's client part on a private bus, started and stopped with ToothSpin."""

    def __init__(self, runtime: Path) -> None:
        self._dir = runtime / "obex"
        self._procs: list[asyncio.subprocess.Process] = []
        self._bus: MessageBus | None = None

    @staticmethod
    def available() -> bool:
        return os.access(OBEXD, os.X_OK)

    async def start(self) -> None:
        self._dir.mkdir(mode=0o700, exist_ok=True)
        socket = self._dir / "bus"
        address = f"unix:path={socket}"
        config = self._dir / "bus.conf"
        config.write_text(_BUS_CONFIG.format(address=address))
        self._procs.append(await asyncio.create_subprocess_exec(
            "dbus-daemon", f"--config-file={config}", "--nofork", "--nopidfile",
        ))
        for _ in range(50):
            if socket.exists():
                break
            await asyncio.sleep(0.1)
        self._procs.append(await asyncio.create_subprocess_exec(
            OBEXD, "--nodetach", "--plugin=client",
            env={**os.environ, "DBUS_SESSION_BUS_ADDRESS": address},
        ))
        self._bus = await MessageBus(bus_address=address).connect()
        for _ in range(50):
            reply = await dbus.call(
                self._bus, "org.freedesktop.DBus", "/org/freedesktop/DBus",
                "org.freedesktop.DBus", "NameHasOwner", "s", [OBEX],
            )
            if reply.body[0]:
                return
            await asyncio.sleep(0.1)
        raise RuntimeError("obexd did not start")

    async def stop(self) -> None:
        if self._bus is not None:
            self._bus.disconnect()
        for proc in reversed(self._procs):
            if proc.returncode is None:
                proc.terminate()
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(proc.wait(), 5)

    async def open(self, address: str, port: int) -> str:
        assert self._bus is not None
        reply = await dbus.call(
            self._bus, OBEX, OBEX_PATH, "org.bluez.obex.Client1", "CreateSession", "sa{sv}",
            [address, {"Target": Variant("s", "bip-avrcp"), "PSM": Variant("q", port)}],
        )
        return reply.body[0]

    async def close(self, session: str) -> None:
        assert self._bus is not None
        await dbus.call(
            self._bus, OBEX, OBEX_PATH, "org.bluez.obex.Client1", "RemoveSession", "o", [session]
        )

    async def fetch(self, session: str, handle: str) -> bytes:
        assert self._bus is not None
        # Android only hands out a cover in a format it names; the thumbnail
        # (200x200 JPEG) is the one every phone has to offer.
        target = self._dir / f"{uuid.uuid4().hex}.jpg"
        reply = await dbus.call(
            self._bus, OBEX, session, "org.bluez.obex.Image1", "GetThumbnail", "ss",
            [str(target), handle],
        )
        transfer = reply.body[0]
        try:
            while True:
                await asyncio.sleep(0.2)
                try:
                    status = await dbus.call(
                        self._bus, OBEX, transfer, dbus.PROPERTIES, "Get", "ss",
                        ["org.bluez.obex.Transfer1", "Status"],
                    )
                except DBusError:
                    break  # obexd drops a transfer once it's done
                if status.body[0].value == "error":
                    raise OSError("the phone refused the cover")
                if status.body[0].value == "complete":
                    break
            cover = target.read_bytes() if target.exists() else b""
            if not cover:
                raise OSError("the phone refused the cover")
            return cover
        finally:
            target.unlink(missing_ok=True)
