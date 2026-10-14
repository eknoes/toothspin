"""Sendspin source-role client: streams captured PCM to Music Assistant on request."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import stat
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from aiohttp import ClientError
from aiosendspin.client import PairingSupport, SendspinClient
from aiosendspin.models.core import DeviceInfo
from aiosendspin.models.player import SupportedAudioFormat
from aiosendspin.models.source import ClientHelloSourceFeatures, ClientHelloSourceSupport
from aiosendspin.models.types import AudioCodec, GoodbyeReason, Roles, SignalState
from aiosendspin.noise import FileClientPairingStore, Identity, b64url_decode, b64url_encode
from aiosendspin.noise.trust_store import PairingPsk

from .pipewire import CAPTURE_FORMAT, PcmFormat

if TYPE_CHECKING:
    from aiosendspin.client.source import SourceCapture
    from aiosendspin.models.core import ServerCommandPayload

logger = logging.getLogger(__name__)

# Music Assistant gives up on an input that sends nothing within 5 s of being
# asked to start, and the speaker turns off again. Right after Connect the
# phone isn't playing yet: until it does, send silence (for at most this long).
COLD_START_FILL_S = 120.0
FILL_CHUNK_MS = 20


@dataclass(slots=True)
class SourceStatus:
    name: str
    url: str | None
    connected: bool
    server_name: str | None
    paired: bool
    requested: bool
    """Music Assistant asked for this input's audio."""
    streaming: bool
    """The stream to Music Assistant is set up (lags ``requested`` briefly)."""
    signal: bool
    pairing_window_open: bool
    pairing_requested: bool
    pin: str | None


class SendspinSource:
    def __init__(
        self,
        name: str,
        url: str | None,
        data_dir: Path,
        codec: AudioCodec = AudioCodec.PCM,
        device_info: DeviceInfo | None = None,
        pin_pairing: bool = True,
    ) -> None:
        self._name = name
        self._device_info = device_info
        # Without, servers can only pair through a pre-shared key that ToothSpin
        # hands over itself (its own server, or Music Assistant via its API).
        self._pin_pairing = pin_pairing
        # Set when the phone was removed: say goodbye for good.
        self.leaving = False
        self._url = url
        self._data_dir = data_dir
        self._codec = codec
        self._client: SendspinClient | None = None
        self._store: FileClientPairingStore | None = None
        self._paired_servers: set[str] = set()
        self._lock = asyncio.Lock()
        self._start_requested = False
        self._started_at = 0.0
        self._audio_since_start = False
        self._stopped_at = 0.0
        self._capture: SourceCapture | None = None
        self._format = CAPTURE_FORMAT
        self._signal = False
        self._sent_signal: tuple[object, bool] | None = None
        self._pin: str | None = None
        self._pairing_requested = False

    @property
    def client(self) -> SendspinClient:
        assert self._client is not None
        return self._client

    async def setup(self) -> None:
        self._data_dir.mkdir(parents=True, exist_ok=True)
        identity = _load_identity(self._data_dir / "identity.json")
        self._store = await FileClientPairingStore.open(self._data_dir / "pairing-store.json")
        self._client = SendspinClient(
            identity=identity,
            client_name=self._name,
            roles=[Roles.SOURCE],
            pairing_store=self._store,
            device_info=self._device_info,
            pairing_support=PairingSupport(
                pin_display=self._on_pin,
                gesture_prompt=self._on_gesture_prompt,
                offer_static_pin=False,
            )
            if self._pin_pairing
            else None,
            source_support=ClientHelloSourceSupport(
                features=ClientHelloSourceFeatures(line_sense=True)
            ),
        )
        self._client.add_server_command_listener(self._on_command)
        await self._refresh_paired()
        logger.info("Sendspin client id %s", identity.peer_id)

    # --- connection ---

    async def run(self) -> None:
        """Stay connected to the server, reconnecting with backoff."""
        signal_task = asyncio.create_task(self._signal_loop())
        fill_task = asyncio.create_task(self._fill_loop())
        try:
            backoff = 1.0
            while True:
                url = self._url or await _discover_server()
                if url is None:
                    logger.warning("No Sendspin server found; retrying in %.0fs", backoff)
                else:
                    try:
                        await self.client.connect(url)
                        self._url = self._url or url
                        backoff = 1.0
                        disconnected = asyncio.Event()
                        remove = self.client.add_disconnect_listener(disconnected.set)
                        await disconnected.wait()
                        remove()
                        logger.info("Disconnected from %s", url)
                    except (TimeoutError, OSError, ClientError, RuntimeError) as err:
                        logger.warning("Connecting to %s failed: %s", url, err)
                    await self._reset()
                    await self._refresh_paired()
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60.0)
        finally:
            signal_task.cancel()
            fill_task.cancel()
            # RESTART, not SHUTDOWN: the service always comes back, and on
            # SHUTDOWN the server drops the client, so Music Assistant forgets
            # it was playing this input and never asks for it again. Which is
            # what we want once the phone was removed.
            await self.client.disconnect(
                GoodbyeReason.SHUTDOWN if self.leaving else GoodbyeReason.RESTART
            )

    async def _reset(self) -> None:
        async with self._lock:
            self._start_requested = False
            await self._stop_capture()
        self._sent_signal = None

    # --- streaming ---

    def _on_command(self, payload: ServerCommandPayload) -> None:
        if payload.source is None:
            return
        logger.info("Server source command: %s", payload.source.command)
        if payload.source.command == "start":
            asyncio.ensure_future(self._handle_start())
        elif payload.source.command == "stop":
            asyncio.ensure_future(self._handle_stop())

    async def _handle_start(self) -> None:
        async with self._lock:
            self._start_requested = True
            self._started_at = time.monotonic()
            self._audio_since_start = False
            await self._start_capture(self._format)

    async def _handle_stop(self) -> None:
        async with self._lock:
            self._start_requested = False
            self._stopped_at = time.monotonic()
            await self._stop_capture()

    async def push(self, pcm: bytes, fmt: PcmFormat, timestamp_us: int) -> None:
        """Feed captured PCM; it's only sent while the server has asked for audio."""
        self._audio_since_start = True
        await self._send(pcm, fmt, timestamp_us)

    async def _fill_loop(self) -> None:
        """Send silence while the server waits for the phone to start playing."""
        chunk_us = FILL_CHUNK_MS * 1000
        next_ts: int | None = None
        while True:
            await asyncio.sleep(FILL_CHUNK_MS / 1000)
            if (
                not self._start_requested
                or self._audio_since_start
                or time.monotonic() - self._started_at > COLD_START_FILL_S
                or not self.client.connected
            ):
                next_ts = None
                continue
            fmt = self._format
            silence = bytes(fmt.channels * fmt.bit_depth // 8 * fmt.sample_rate * FILL_CHUNK_MS // 1000)
            now = self.client.now_us()
            # Chunks end "now", like the phone's: its audio then follows on.
            if next_ts is None or now - next_ts > 10 * chunk_us:
                next_ts = now - chunk_us
            while next_ts + chunk_us <= now and not self._audio_since_start:
                await self._send(silence, fmt, next_ts)
                next_ts += chunk_us

    async def _send(self, pcm: bytes, fmt: PcmFormat, timestamp_us: int) -> None:
        async with self._lock:
            if fmt != self._format:
                self._format = fmt
                if self._capture is not None:
                    logger.info("Capture format changed; restarting stream")
                    await self._stop_capture()
            if not self._start_requested:
                return
            if self._capture is None:
                await self._start_capture(fmt)
            if self._capture is None:
                return
            try:
                await self._capture.feed(pcm, timestamp_us)
            except RuntimeError as err:
                logger.warning("Dropping capture stream: %s", err)
                self._capture = None

    async def _start_capture(self, fmt: PcmFormat) -> None:
        if self._capture is not None:
            return
        capture = self.client.create_source_capture(
            SupportedAudioFormat(
                codec=self._codec,
                sample_rate=fmt.sample_rate,
                bit_depth=fmt.bit_depth,
                channels=fmt.channels,
            )
        )
        try:
            await capture.start()
        except RuntimeError as err:
            # Typically "clock not synchronized" right after connecting; the
            # next pushed chunk retries.
            logger.debug("Capture start deferred: %s", err)
            return
        self._capture = capture
        logger.info(
            "Streaming to server (%s, %d Hz, %d ch)",
            self._codec.value,
            fmt.sample_rate,
            fmt.channels,
        )

    async def _stop_capture(self) -> None:
        capture, self._capture = self._capture, None
        if capture is None:
            return
        try:
            await capture.stop()
        except (RuntimeError, ConnectionError) as err:
            logger.debug("Capture stop failed: %s", err)
        logger.info("Streaming stopped")

    # --- line sense ---

    def set_signal(self, present: bool) -> None:
        self._signal = present

    async def _signal_loop(self) -> None:
        """Report signal presence on change and once per (re)connection.

        Only paired connections accept source state, so failures are expected
        until pairing completes and simply retried.
        """
        while True:
            await asyncio.sleep(1.0)
            await self._refresh_paired()
            connection = self.client._admitted_connection  # noqa: SLF001
            if connection is None:
                continue
            state = (connection, self._signal)
            if state == self._sent_signal:
                continue
            try:
                await connection.send_source_signal(
                    SignalState.PRESENT if self._signal else SignalState.ABSENT
                )
            except (RuntimeError, ConnectionError):
                continue
            self._sent_signal = state
            logger.info("Reported signal %s", "present" if self._signal else "absent")

    # --- pairing ---

    def open_pairing_window(self) -> None:
        self.client.open_pairing_window()

    async def paired_with(self, server_id: str) -> bool:
        assert self._store is not None
        return await self._store.record_by_server_id(server_id) is not None

    async def accept_pairing(self, pairing: PairingPsk) -> None:
        """Pair with the next server that presents this pre-shared key.

        The server side stages the same key: no PIN, for servers that are
        already trusted (ToothSpin's own, or Music Assistant via its API).
        """
        assert self._store is not None
        await self._store.set_pairing_psk(pairing)

    async def _on_pin(self, pin: str | None) -> None:
        self._pin = pin
        if pin is None:
            await self._refresh_paired()

    async def _on_gesture_prompt(self, waiting: bool) -> None:
        self._pairing_requested = waiting

    async def _refresh_paired(self) -> None:
        # The store also holds a seeded fallback record with no server_id.
        assert self._store is not None
        records = await self._store.list_records()
        self._paired_servers = {r.server_id for r in records if r.server_id}

    def status(self) -> SourceStatus:
        client = self.client
        info = client.server_info if client.connected else None
        return SourceStatus(
            name=self._name,
            url=self._url,
            connected=client.connected,
            server_name=info.name if info else None,
            paired=info.server_id in self._paired_servers if info else bool(self._paired_servers),
            # MA stops and restarts the input whenever its speakers regroup;
            # don't flicker to "not playing" for that.
            requested=self._start_requested or time.monotonic() - self._stopped_at < 2.0,
            streaming=self._capture is not None,
            signal=self._signal,
            pairing_window_open=client.pairing_window_open,
            pairing_requested=self._pairing_requested,
            pin=self._pin,
        )


def _load_identity(path: Path) -> Identity:
    """Load the persistent Noise identity; its public key is our client_id."""
    try:
        return Identity.from_private_bytes(
            b64url_decode(json.loads(path.read_text())["private_key"])
        )
    except FileNotFoundError:
        pass
    identity = Identity.generate()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, stat.S_IRUSR | stat.S_IWUSR)
    with os.fdopen(fd, "w") as handle:
        json.dump({"private_key": b64url_encode(identity.private_bytes)}, handle)
    return identity


async def _discover_server(timeout: float = 3.0) -> str | None:
    """Find a Sendspin server (e.g. Music Assistant) via mDNS."""
    from zeroconf import ServiceStateChange
    from zeroconf.asyncio import AsyncServiceBrowser, AsyncServiceInfo, AsyncZeroconf

    service_type = "_sendspin-server._tcp.local."
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
            addresses = info.parsed_addresses()
            if not addresses or info.port is None:
                continue
            path = (info.properties.get(b"path") or b"/sendspin").decode()
            return f"ws://{addresses[0]}:{info.port}{path}"
    return None
