"""Capture backend: the phone's PipeWire node -> Sendspin source.

Records whichever phone is currently connected, timestamps the audio on the
Sendspin client clock and derives line-sense (signal present) from its level.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import math
from collections.abc import AsyncIterator, Awaitable, Callable

import numpy as np

from . import pipewire
from .pipewire import CAPTURE_FORMAT, Source
from .source import SendspinSource

logger = logging.getLogger(__name__)

CHUNK_MS = 20
SIGNAL_THRESHOLD_DBFS = -60.0
# Silence this long counts as "signal gone" (pause, end of playlist).
SIGNAL_HOLD_S = 5.0
# Arrival jitter beyond this resyncs the timeline instead of smoothing it.
RESYNC_US = 200_000
# How often to look for a phone node appearing or disappearing.
POLL_S = 2.0


class Capture:
    def __init__(
        self,
        source: SendspinSource,
        now_us: Callable[[], int],
        find_source: Callable[[], Awaitable[Source | None]] = pipewire.find_source,
        record: Callable[[Source, int], AsyncIterator[bytes]] = pipewire.record,
    ) -> None:
        self._source = source
        self._now_us = now_us
        self._find_source = find_source
        self._record = record
        self._changed = asyncio.Event()
        self._last_loud_us: int | None = None
        self.active: Source | None = None

    def notify(self) -> None:
        """Called on Bluetooth changes, to look for the node right away."""
        self._changed.set()

    async def run(self) -> None:
        signal_task = asyncio.create_task(self._signal_loop())
        try:
            while True:
                found = await self._find_source()
                if found is None:
                    await self._wait_change()
                    continue
                capture = asyncio.create_task(self._capture(found))
                while not capture.done():
                    await asyncio.wait({capture}, timeout=POLL_S)
                    if not capture.done() and await self._find_source() != found:
                        capture.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await capture
                # Don't respawn pw-record in a tight loop if it keeps failing.
                await asyncio.sleep(0.5)
        finally:
            signal_task.cancel()

    async def _wait_change(self) -> None:
        self._changed.clear()
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._changed.wait(), POLL_S)

    async def _capture(self, found: Source) -> None:
        fmt = CAPTURE_FORMAT
        frames = fmt.sample_rate * CHUNK_MS // 1000
        chunk_us = frames * 1_000_000 // fmt.sample_rate
        logger.info("Capturing %s (%s)", found.description, found.codec)
        self.active = found
        next_ts: int | None = None
        try:
            async for chunk in self._record(found, frames):
                now = self._now_us()
                arrived = now - chunk_us
                # Bluetooth delivers in bursts; keep a steady timeline and only
                # nudge it towards arrival time so jitter doesn't reach MA.
                if next_ts is None or abs(arrived - next_ts) > RESYNC_US:
                    next_ts = arrived
                else:
                    next_ts += (arrived - next_ts) // 64
                if _dbfs(chunk) > SIGNAL_THRESHOLD_DBFS:
                    self._last_loud_us = now
                await self._source.push(chunk, fmt, next_ts)
                next_ts += chunk_us
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Capture from %s failed", found.node_name)
            await asyncio.sleep(1.0)
        finally:
            self.active = None
            logger.info("Capture from %s ended", found.description)

    async def _signal_loop(self) -> None:
        while True:
            last = self._last_loud_us
            present = (
                self.active is not None
                and last is not None
                and self._now_us() - last < SIGNAL_HOLD_S * 1_000_000
            )
            self._source.set_signal(present)
            await asyncio.sleep(0.5)


def _dbfs(pcm: bytes) -> float:
    """RMS level of interleaved S16LE PCM in dBFS."""
    samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32)
    if not samples.size:
        return -math.inf
    mean_square = float(np.mean(samples * samples))
    if mean_square == 0:
        return -math.inf
    return 10 * math.log10(mean_square / (32768.0 * 32768.0))
