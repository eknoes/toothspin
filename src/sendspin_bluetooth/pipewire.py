"""Find the phone's PipeWire capture node and record from it.

PipeWire (with WirePlumber's ``bluez5.media-source-role = input``) exposes a
connected phone as an ``Audio/Source`` node. We locate it with ``pw-dump``
and read raw PCM from ``pw-record``, which also resamples to one fixed
format, so codec renegotiation on the phone never reaches the Sendspin side.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PcmFormat:
    sample_rate: int
    channels: int
    bit_depth: int = 16

    @property
    def frame_bytes(self) -> int:
        return self.channels * self.bit_depth // 8


# What Music Assistant's source bridge outputs anyway, so resample once here.
CAPTURE_FORMAT = PcmFormat(sample_rate=48000, channels=2)


@dataclass(frozen=True, slots=True)
class Source:
    node_name: str
    description: str
    address: str
    codec: str


def parse_sources(dump: list[dict]) -> list[Source]:
    """Bluetooth capture nodes in ``pw-dump`` output."""
    sources = []
    for obj in dump:
        if not obj.get("type", "").endswith(":Node"):
            continue
        props = (obj.get("info") or {}).get("props") or {}
        if props.get("media.class") != "Audio/Source" or "api.bluez5.address" not in props:
            continue
        sources.append(
            Source(
                node_name=props.get("node.name", ""),
                description=props.get("node.description") or props["api.bluez5.address"],
                address=props["api.bluez5.address"],
                codec=str(props.get("api.bluez5.codec", "")).upper(),
            )
        )
    return sources


async def find_source() -> Source | None:
    """The phone currently exposed as a capture node (we serve one at a time)."""
    proc = await asyncio.create_subprocess_exec(
        "pw-dump",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    if proc.returncode != 0:
        logger.warning("pw-dump failed: %s", err.decode(errors="replace").strip())
        return None
    sources = parse_sources(json.loads(out or b"[]"))
    return sources[0] if sources else None


async def record(source: Source, chunk_frames: int) -> AsyncIterator[bytes]:
    """Yield whole-frame PCM chunks in ``CAPTURE_FORMAT`` until pw-record exits."""
    fmt = CAPTURE_FORMAT
    proc = await asyncio.create_subprocess_exec(
        "pw-record",
        "--raw",
        f"--target={source.node_name}",
        f"--rate={fmt.sample_rate}",
        f"--channels={fmt.channels}",
        "--format=s16",
        "--latency=20ms",
        "-P", "{ node.name = sendspin-bluetooth }",
        "-",
        stdout=asyncio.subprocess.PIPE,
    )
    assert proc.stdout is not None
    chunk_bytes = chunk_frames * fmt.frame_bytes
    try:
        while True:
            try:
                yield await proc.stdout.readexactly(chunk_bytes)
            except asyncio.IncompleteReadError:
                return
    finally:
        if proc.returncode is None:
            proc.terminate()
        await proc.wait()
