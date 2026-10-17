"""Run PipeWire + WirePlumber alongside the service (self-contained image).

The image doesn't rely on a desktop audio session: it starts its own
PipeWire, which registers the A2DP sink with the host's bluetoothd over the
system D-Bus. If either process exits, the service exits too, so the
container (or HA add-on) gets restarted cleanly.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import stat
from pathlib import Path

logger = logging.getLogger(__name__)

# Where PipeWire keeps its socket unless XDG_RUNTIME_DIR says otherwise (the
# image sets it). Checked to be ToothSpin's own before use.
DEFAULT_RUNTIME = "/tmp/toothspin-runtime"  # noqa: S108


class AudioStack:
    def __init__(self) -> None:
        runtime = os.environ.setdefault("XDG_RUNTIME_DIR", DEFAULT_RUNTIME)
        self._runtime = Path(runtime)
        self._procs: list[asyncio.subprocess.Process] = []
        self.exited = asyncio.Event()

    async def start(self) -> None:
        self._runtime.mkdir(mode=0o700, parents=True, exist_ok=True)
        # A folder someone else made (or a link to one) could hand them
        # PipeWire's socket, or point it elsewhere.
        info = self._runtime.lstat()
        if (
            not stat.S_ISDIR(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_mode & 0o077
        ):
            raise RuntimeError(f"{self._runtime} isn't a private folder of ToothSpin's user")
        await self._spawn("pipewire")
        socket = self._runtime / "pipewire-0"
        for _ in range(100):
            if socket.exists():
                break
            await asyncio.sleep(0.1)
        else:
            raise RuntimeError("PipeWire did not start")
        await self._spawn("wireplumber")
        logger.info("Started bundled PipeWire and WirePlumber")

    async def _spawn(self, program: str) -> None:
        proc = await asyncio.create_subprocess_exec(program)
        self._procs.append(proc)
        asyncio.ensure_future(self._watch(program, proc))

    async def _watch(self, program: str, proc: asyncio.subprocess.Process) -> None:
        code = await proc.wait()
        if not self.exited.is_set():
            logger.error("%s exited with %s", program, code)
            self.exited.set()

    async def stop(self) -> None:
        self.exited.set()
        for proc in reversed(self._procs):
            if proc.returncode is None:
                proc.terminate()
        for proc in self._procs:
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(proc.wait(), 5)
            if proc.returncode is None:
                proc.kill()
