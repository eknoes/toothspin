"""Capture backend: the phone's PipeWire node -> Sendspin source.

Records one phone's PipeWire node, timestamps the audio on the
Sendspin client clock and derives line-sense (signal present) from its level.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import math
import operator
import sys
from collections.abc import AsyncIterator, Awaitable, Callable
from functools import partial

from array import array

from . import pipewire
from .pipewire import CAPTURE_FORMAT, Source
from .source import FILL_GAP_S, PAUSE_FILL_S, SendspinSource

logger = logging.getLogger(__name__)

CHUNK_MS = 20
SIGNAL_THRESHOLD_DBFS = -60.0
# Silence this long counts as "signal gone". Music Assistant stops an input
# 60 s after its signal goes, so a short one would end every pause; the
# speakers are kept as long as the source fills a pause with silence.
SIGNAL_HOLD_S = PAUSE_FILL_S
# Arrival jitter beyond this resyncs the timeline instead of smoothing it.
RESYNC_US = 200_000
# How often to look for a phone node appearing or disappearing.
POLL_S = 2.0
# After a Bluetooth change, look this often for this long: PipeWire creates
# the node only once the phone starts its stream.
BURST_POLL_S = 0.25
BURST_S = 4.0
# Report late audio (a gap the source fills with silence) at most this often.
LATE_REPORT_S = 60.0


class Capture:
    """Records one phone, identified by its Bluetooth address."""

    def __init__(
        self,
        address: str,
        source: SendspinSource,
        now_us: Callable[[], int],
        find_source: Callable[[str], Awaitable[Source | None]] = pipewire.find_source,
        record: Callable[[Source, int], AsyncIterator[bytes]] = pipewire.record,
    ) -> None:
        self._source = source
        self._now_us = now_us
        self._find_source = partial(find_source, address)
        self._record = record
        self._changed = asyncio.Event()
        self._burst_until = 0.0
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
        loop = asyncio.get_running_loop()
        if loop.time() < self._burst_until:
            await asyncio.sleep(BURST_POLL_S)
            return
        self._changed.clear()
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._changed.wait(), POLL_S)
        if self._changed.is_set():
            self._burst_until = loop.time() + BURST_S

    async def _capture(self, found: Source) -> None:
        fmt = CAPTURE_FORMAT
        frames = fmt.sample_rate * CHUNK_MS // 1000
        chunk_us = frames * 1_000_000 // fmt.sample_rate
        logger.info("Capturing %s (%s)", found.description, found.codec)
        self.active = found
        next_ts: int | None = None
        late = _LateAudio(found.description, self._now_us())
        try:
            async for chunk in self._record(found, frames):
                now = self._now_us()
                late.arrived(now)
                arrived = now - chunk_us
                # Bluetooth delivers in bursts; keep a steady timeline and only
                # nudge it towards arrival time so jitter doesn't reach MA.
                if next_ts is None or abs(arrived - next_ts) > RESYNC_US:
                    if next_ts is not None:
                        late.resyncs += 1
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
            late.summary(self._now_us())
            logger.info("Capture from %s ended", found.description)

    async def _signal_loop(self) -> None:
        while True:
            last = self._last_loud_us
            # Also while paused: the phone stops its stream then, and the
            # capture ends.
            present = last is not None and self._now_us() - last < SIGNAL_HOLD_S * 1_000_000
            self._source.set_signal(present)
            await asyncio.sleep(0.5)


class _LateAudio:
    """Counts gaps in a phone's audio: a weak Bluetooth link stutters there."""

    def __init__(self, name: str, now_us: int) -> None:
        self._name = name
        self._started_us = self._since_us = now_us
        self._last_us: int | None = None
        self.gaps = 0
        self.longest_us = 0
        self.resyncs = 0
        # The whole session, for the summary when the phone stops.
        self._total_gaps = 0
        self._total_longest_us = 0

    def arrived(self, now_us: int) -> None:
        if self._last_us is not None:
            gap = now_us - self._last_us
            if gap > FILL_GAP_S * 1_000_000:
                self.gaps += 1
                self.longest_us = max(self.longest_us, gap)
                self._total_gaps += 1
                self._total_longest_us = max(self._total_longest_us, gap)
        self._last_us = now_us
        if now_us - self._since_us >= LATE_REPORT_S * 1_000_000:
            self.report(now_us)

    def report(self, now_us: int) -> None:
        if self.gaps or self.resyncs:
            logger.info(
                "%s: audio came late %d times in %.0f s (longest gap %d ms), timing restarted %d times",
                self._name,
                self.gaps,
                (now_us - self._since_us) / 1_000_000,
                self.longest_us // 1000,
                self.resyncs,
            )
        self._since_us = now_us
        self.gaps = self.longest_us = self.resyncs = 0

    def summary(self, now_us: int) -> None:
        """How the Bluetooth link did over the whole session."""
        self.report(now_us)
        minutes = (now_us - self._started_us) / 60_000_000
        if self._total_gaps:
            logger.info(
                "%s played for %.0f min; Bluetooth audio came late %d times (longest %d ms)",
                self._name, minutes, self._total_gaps, self._total_longest_us // 1000,
            )
        else:
            logger.info("%s played for %.0f min without Bluetooth gaps", self._name, minutes)


def _dbfs(pcm: bytes) -> float:
    """RMS level of interleaved S16LE PCM in dBFS."""
    samples = array("h", pcm)
    if sys.byteorder != "little":
        samples.byteswap()
    if not samples:
        return -math.inf
    mean_square = sum(map(operator.mul, samples, samples)) / len(samples)
    if mean_square == 0:
        return -math.inf
    return 10 * math.log10(mean_square / (32768.0 * 32768.0))
