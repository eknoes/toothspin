"""One Sendspin source per paired phone, so each is its own input in Music Assistant.

Each phone gets its own Sendspin identity and pairing store, so it's paired
with Music Assistant once, separately. Removing the phone deletes both.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import shutil
from importlib.metadata import version
from dataclasses import dataclass
from pathlib import Path

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
    ) -> None:
        self._bluetooth = bluetooth
        self._data_dir = data_dir / "devices"
        self._url = url
        self._codec = codec
        self._name_format = name_format
        self._device_info = DeviceInfo(
            manufacturer=manufacturer,
            product_name="Bluetooth receiver",
            software_version=version("sendspin-bluetooth"),
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
                await self._remove(address)
            for address, device in paired.items():
                if address not in self._receivers:
                    await self._add(address, device.name)

    async def rename(self, address: str, name: str) -> None:
        """Rename a phone's input; its client reconnects with the new name."""
        address = address.upper()
        if address not in self._receivers:
            raise KeyError(address)
        async with self._sync_lock:
            settings = self._settings_path(address)
            settings.write_text(json.dumps({"name": name}))
            await self._stop(address)
            device_name = next(
                (d.name for d in self._bluetooth.devices() if d.address.upper() == address),
                address,
            )
            await self._add(address, device_name)
        logger.info("Renamed Sendspin source for %s to %s", address, name)

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

    def _name_for(self, address: str, device_name: str) -> str:
        """The name chosen in the web UI, else one derived from the phone's."""
        try:
            return json.loads(self._settings_path(address).read_text())["name"]
        except (FileNotFoundError, KeyError, ValueError):
            return self._name_format.format(device=device_name)

    async def _add(self, address: str, device_name: str) -> None:
        source = SendspinSource(
            self._name_for(address, device_name),
            self._url,
            self._device_dir(address),
            self._codec,
            self._device_info,
        )
        await source.setup()
        capture = Capture(address, source, source.client.now_us)
        task = asyncio.create_task(_run(source, capture), name=f"receiver {address}")
        task.add_done_callback(self._on_done)
        self._receivers[address] = Receiver(address, source, capture, task)
        logger.info("Added Sendspin source for %s (%s)", device_name, address)

    async def _stop(self, address: str) -> None:
        receiver = self._receivers.pop(address)
        receiver.task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await receiver.task

    async def _remove(self, address: str) -> None:
        await self._stop(address)
        # The phone was unpaired: forget its Sendspin identity too, so pairing
        # it again starts fresh on both layers.
        shutil.rmtree(self._device_dir(address), ignore_errors=True)
        logger.info("Removed Sendspin source for %s", address)


async def _run(source: SendspinSource, capture: Capture) -> None:
    tasks = [asyncio.create_task(source.run()), asyncio.create_task(capture.run())]
    try:
        await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
