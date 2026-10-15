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


def test_signal_outlasts_a_pause_but_not_the_hold(monkeypatch) -> None:
    from toothspin import capture as capture_module

    clock = [0]
    reports: list[bool] = []
    source = FakeSource()
    source.set_signal = reports.append  # type: ignore[method-assign]
    loud = np.full(CHUNK_MS * 48, 8000, dtype="<i2").tobytes() * 2

    async def record(found: Source, frames: int):
        for i in range(5):
            clock[0] = 1_000_000 + i * CHUNK_US
            yield loud

    async def scenario() -> None:
        capture = Capture(PHONE.address, source, lambda: clock[0], record=record)  # type: ignore[arg-type]
        await capture._capture(PHONE)  # played, then the phone paused: capture ended
        monkeypatch.setattr(capture_module.asyncio, "sleep", _stop_after_one)
        for minutes in (1, capture_module.SIGNAL_HOLD_S / 60 + 1):
            clock[0] = 1_000_000 + int(minutes * 60_000_000)
            try:
                await capture._signal_loop()
            except _Stop:
                pass

    asyncio.run(scenario())
    assert reports == [True, False]  # still there a minute into the pause, gone after the hold


class _Stop(Exception):
    pass


async def _stop_after_one(_seconds: float) -> None:
    raise _Stop


def test_reports_late_audio(caplog) -> None:
    caplog.set_level("INFO", logger="toothspin.capture")
    arrivals = [1_000_000 + i * CHUNK_US for i in range(10)]
    arrivals += [1_800_000 + i * CHUNK_US for i in range(10)]
    _run(arrivals)
    assert "Pixel: audio came late 1 times" in caplog.text
    assert "longest gap 620 ms), timing restarted 1 times" in caplog.text


def test_steady_audio_reports_nothing(caplog) -> None:
    caplog.set_level("INFO", logger="toothspin.capture")
    _run([1_000_000 + i * CHUNK_US for i in range(20)])
    assert "came late" not in caplog.text
