"""Home Assistant's own audio service, which also receives Bluetooth audio.

The Supervisor's audio plugin (hassio_audio, PulseAudio) loads
module-bluetooth-discover: it registers its own A2DP sink with the host's
BlueZ, next to ToothSpin's PipeWire, and takes a phone's stream whenever the
phone (or BlueZ) picks its endpoint. The phone then shows as connected, but
its audio never reaches ToothSpin. An App with ``audio: true`` can reach the
plugin's PulseAudio and unload those modules; the plugin loads them again
when it restarts. ToothSpin only does that with the user's consent.
"""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

SOCKET = Path("/run/audio/pulse.sock")
DISCOVER = ("module-bluetooth-discover", "module-bluez5-discover")
DEVICE = "module-bluez5-device"
_DEVICE_PATH = re.compile(r"path=/org/bluez/hci\d+/dev_([0-9A-F_]{17})", re.IGNORECASE)


class AudioServiceError(Exception):
    pass


def available(socket: Path = SOCKET) -> bool:
    """Whether Home Assistant's audio service is reachable (App with audio: true)."""
    return socket.exists() and shutil.which("pactl") is not None


async def bluetooth_modules(socket: Path = SOCKET) -> list[tuple[str, str, str]]:
    """Its Bluetooth modules as (index, name, arguments)."""
    out = await _pactl(socket, "list", "modules", "short")
    modules = []
    for line in out.splitlines():
        index, name, args = ([*line.split("\t"), "", ""])[:3]
        if name in DISCOVER or name == DEVICE:
            modules.append((index, name, args))
    return modules


async def release(socket: Path = SOCKET) -> list[str]:
    """Unload its Bluetooth modules; the addresses of the phones it held.

    Discovery first, so it doesn't pick a phone up again, then the modules
    holding phones it already took.
    """
    modules = await bluetooth_modules(socket)
    held: list[str] = []
    for index, name, args in sorted(modules, key=lambda m: m[1] == DEVICE):
        try:
            await _pactl(socket, "unload-module", index)
        except AudioServiceError as err:
            # Unloading discovery also unloads what it loaded.
            logger.debug("Unloading %s (%s): %s", name, index, err)
        if name == DEVICE and (match := _DEVICE_PATH.search(args)):
            held.append(match.group(1).replace("_", ":").upper())
    return held


async def _pactl(socket: Path, *args: str) -> str:
    try:
        proc = await asyncio.create_subprocess_exec(
            "pactl", f"--server=unix:{socket}", *args,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        out, err = await asyncio.wait_for(proc.communicate(), 10)
    except (OSError, TimeoutError) as exc:
        raise AudioServiceError(f"pactl {' '.join(args)}: {exc}") from exc
    if proc.returncode != 0:
        raise AudioServiceError(f"pactl {' '.join(args)}: {err.decode().strip()}")
    return out.decode()
