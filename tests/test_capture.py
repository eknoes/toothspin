import asyncio
import math

import numpy as np

from toothspin.capture import CHUNK_MS, Capture, _dbfs
from toothspin.pipewire import CAPTURE_FORMAT, PcmFormat, Source

CHUNK_US = CHUNK_MS * 1000
PHONE = Source("bluez_input.AA", "Pixel", "AA:BB:CC:DD:EE:FF", "AAC")


def test_dbfs() -> None:
    assert _dbfs(bytes(400)) == -math.inf
    half_scale = np.full(200, 16384, dtype="<i2").tobytes()
    assert abs(_dbfs(half_scale) - (-6.02)) < 0.01


class FakeSource:
    def __init__(self) -> None:
        self.timestamps: list[int] = []

    async def push(self, pcm: bytes, fmt: PcmFormat, timestamp_us: int) -> None:
        assert fmt == CAPTURE_FORMAT
        self.timestamps.append(timestamp_us)

    def set_signal(self, present: bool) -> None:
        pass


def _run(arrivals: list[int]) -> list[int]:
    clock = [0]
    source = FakeSource()

    async def record(found: Source, frames: int):
        for arrival in arrivals:
            clock[0] = arrival
            yield bytes(frames * CAPTURE_FORMAT.frame_bytes)

    capture = Capture(PHONE.address, source, lambda: clock[0], record=record)  # type: ignore[arg-type]
    asyncio.run(capture._capture(PHONE))
    return source.timestamps


def test_bursty_arrival_gives_steady_timeline() -> None:
    # Chunks arrive in bursts of 4 every 80 ms.
    arrivals = [1_000_000 + (i // 4) * 4 * CHUNK_US + (i % 4) * 50 for i in range(40)]
    timestamps = _run(arrivals)
    steps = {b - a for a, b in zip(timestamps, timestamps[1:])}
    assert max(steps) - min(steps) < 2_000


def test_gap_resyncs_timeline() -> None:
    arrivals = [1_000_000 + i * CHUNK_US for i in range(10)]
    arrivals += [5_000_000 + i * CHUNK_US for i in range(10)]
    timestamps = _run(arrivals)
    assert timestamps[10] == 5_000_000 - CHUNK_US


def test_stops_recording_when_node_disappears() -> None:
    present = [True]
    stopped = asyncio.Event()

    async def find(address: str):
        assert address == PHONE.address
        return PHONE if present[0] else None

    async def record(found: Source, frames: int):
        try:
            while True:
                await asyncio.sleep(0.01)
                yield bytes(frames * CAPTURE_FORMAT.frame_bytes)
        finally:
            stopped.set()

    async def scenario() -> None:
        capture = Capture(
            PHONE.address, FakeSource(), lambda: 0, find_source=find, record=record  # type: ignore[arg-type]
        )
        task = asyncio.create_task(capture.run())
        await asyncio.sleep(0.1)
        assert capture.active == PHONE
        present[0] = False
        await asyncio.wait_for(stopped.wait(), timeout=5)
        assert capture.active is None
        task.cancel()

    asyncio.run(scenario())
