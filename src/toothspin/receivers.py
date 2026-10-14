"""One Sendspin source per paired phone, so each is its own input in Music Assistant.

Each phone gets its own Sendspin identity and pairing store, so it's paired
with Music Assistant once, separately. Only removing the phone in the web
UI deletes both (``forget``); a phone merely vanishing from BlueZ, as on a
bluetoothd restart, just stops its client.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import shutil
from collections.abc import Awaitable, Callable, Coroutine
from importlib.metadata import version
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aiosendspin.models.core import DeviceInfo
from aiosendspin.models.types import AudioCodec

from .bluez import BluetoothManager
from .capture import Capture
from .source import SendspinSource

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class Receiver:
    address: str
    source: SendspinSource
    capture: Capture
    task: asyncio.Task[None]


class Receivers:
    def __init__(
        self,
        bluetooth: BluetoothManager,
        data_dir: Path,
        url: str | None,
        codec: AudioCodec,
        name_format: str,
        manufacturer: str,
        alongside: Callable[[SendspinSource], Coroutine[Any, Any, None]] | None = None,
        pin_pairing: bool = True,
        on_forget: Callable[[str], Awaitable[None]] | None = None,
    ) -> None:
        self._bluetooth = bluetooth
        self._data_dir = data_dir / "devices"
        self._url = url
        self._codec = codec
        self._name_format = name_format
        # E.g. pairing it with Music Assistant through its API, while it runs.
        self._alongside = alongside
        self._pin_pairing = pin_pairing
        # Removing a phone's input from the server too, by its client id.
        self._on_forget = on_forget
        self._forgets: set[asyncio.Task[None]] = set()
        self._device_info = DeviceInfo(
            manufacturer=manufacturer,
            product_name="ToothSpin",
            software_version=version("toothspin"),
        )
        self._receivers: dict[str, Receiver] = {}
        self._sync_lock = asyncio.Lock()
        self._sync_pending = False
        # Set when a receiver dies unexpectedly; the service then exits and
        # systemd restarts it.
        self.failed = asyncio.Event()

    def get(self, address: str) -> Receiver | None:
        return self._receivers.get(address.upper())

    def notify(self) -> None:
        """Bluetooth changed: pick up new/removed phones and nudge the captures."""
        for receiver in self._receivers.values():
            receiver.capture.notify()
        if not self._sync_pending:
            self._sync_pending = True
            asyncio.ensure_future(self.sync())

    async def sync(self) -> None:
        async with self._sync_lock:
            self._sync_pending = False
            paired = {d.address.upper(): d for d in self._bluetooth.devices()}
            for address in set(self._receivers) - set(paired):
                await self._stop(address)
            for address, device in paired.items():
                if address not in self._receivers:
                    await self._add(address, device.name)

    async def rename(self, address: str, name: str) -> None:
        """Rename a phone's input; its client reconnects with the new name."""
        address = address.upper()
        if address not in self._receivers:
            raise KeyError(address)
        async with self._sync_lock:
            self._update_settings(address, name=name)
            await self._stop(address)
            device_name = next(
                (d.name for d in self._bluetooth.devices() if d.address.upper() == address),
                address,
            )
            await self._add(address, device_name)
        logger.info("Renamed Sendspin source for %s to %s", address, name)

    def hidden_speakers(self, address: str) -> list[str]:
        """Speakers this phone's card shows faded at the bottom."""
        return list(self._settings(address.upper()).get("hidden_speakers", []))

    def set_speaker_hidden(self, address: str, player_id: str, hidden: bool) -> None:
        address = address.upper()
        if address not in self._receivers:
            raise KeyError(address)
        current = [p for p in self.hidden_speakers(address) if p != player_id]
        self._update_settings(address, hidden_speakers=current + [player_id] if hidden else current)

    async def close(self) -> None:
        for receiver in self._receivers.values():
            receiver.task.cancel()
        await asyncio.gather(
            *(r.task for r in self._receivers.values()), return_exceptions=True
        )
        self._receivers.clear()

    def _on_done(self, task: asyncio.Task[None]) -> None:
        if not task.cancelled() and task.exception() is not None:
            logger.error("%s failed", task.get_name(), exc_info=task.exception())
            self.failed.set()

    def _device_dir(self, address: str) -> Path:
        return self._data_dir / address.replace(":", "_")

    def _settings_path(self, address: str) -> Path:
        return self._device_dir(address) / "settings.json"

    def _settings(self, address: str) -> dict:
        """Per-phone settings chosen in the web UI (name, hidden speakers)."""
        try:
            settings = json.loads(self._settings_path(address).read_text())
        except (FileNotFoundError, ValueError):
            return {}
        return settings if isinstance(settings, dict) else {}

    def _update_settings(self, address: str, **changes: object) -> None:
        path = self._settings_path(address)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({**self._settings(address), **changes}))
        tmp.replace(path)

    def _name_for(self, address: str, device_name: str) -> str:
        """The name chosen in the web UI, else one derived from the phone's."""
        return self._settings(address).get("name") or self._name_format.format(device=device_name)

    async def _add(self, address: str, device_name: str) -> None:
        source = SendspinSource(
            self._name_for(address, device_name),
            self._url,
            self._device_dir(address),
            self._codec,
            self._device_info,
            pin_pairing=self._pin_pairing,
        )
        await source.setup()
        capture = Capture(address, source, source.client.now_us)
        extra = self._alongside(source) if self._alongside else None
        task = asyncio.create_task(_run(source, capture, extra), name=f"receiver {address}")
        task.add_done_callback(self._on_done)
        self._receivers[address] = Receiver(address, source, capture, task)
        logger.info("Added Sendspin source for %s (%s)", device_name, address)

    async def _stop(self, address: str) -> None:
        receiver = self._receivers.pop(address)
        receiver.task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await receiver.task

    async def forget(self, address: str) -> None:
        """The user removed this phone: drop its client and Sendspin identity."""
        address = address.upper()
        async with self._sync_lock:
            client_id = None
            if (receiver := self._receivers.get(address)) is not None:
                client_id = receiver.source.client.identity.peer_id
                receiver.source.leaving = True
                await self._stop(address)
            # Pairing the phone again then starts fresh on both layers.
            shutil.rmtree(self._device_dir(address), ignore_errors=True)
        logger.info("Removed Sendspin source for %s", address)
        if client_id and self._on_forget is not None:
            # In the background: Music Assistant takes a moment to let go.
            task = asyncio.create_task(self._on_forget(client_id), name=f"forget {address}")
            task.add_done_callback(self._forgets.discard)
            self._forgets.add(task)


async def _run(
    source: SendspinSource, capture: Capture, extra: Coroutine[Any, Any, None] | None
) -> None:
    tasks = [asyncio.create_task(source.run()), asyncio.create_task(capture.run())]
    if extra is not None:
        tasks.append(asyncio.create_task(extra))
    try:
        await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
