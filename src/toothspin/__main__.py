"""Entry point: wire BlueZ, PipeWire capture, the Sendspin source and the web UI."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import socket
from pathlib import Path

from aiohttp import web
from aiosendspin.models.types import AudioCodec
from dbus_fast import BusType
from dbus_fast.aio import MessageBus

from .audio_stack import AudioStack
from .bluez import BluetoothManager
from .ma import MusicAssistant
from .receivers import Receivers
from .web import create_app

logger = logging.getLogger(__name__)


def _parse_args() -> argparse.Namespace:
    env = os.environ.get
    parser = argparse.ArgumentParser(prog="toothspin", description=__doc__)
    parser.add_argument(
        "--url", default=env("SENDSPIN_URL"),
        help="Sendspin server URL, e.g. ws://ma:8927/sendspin (default: discover via mDNS)",
    )
    parser.add_argument(
        "--name", default=env("SENDSPIN_NAME", "{device} (Bluetooth)"),
        help="Name of each phone's input in Music Assistant; {device} is the phone's name",
    )
    parser.add_argument(
        "--bt-name", default=env("BT_NAME", "Music Assistant"),
        help="Bluetooth name phones see",
    )
    parser.add_argument(
        "--manufacturer", default=env("SENDSPIN_MANUFACTURER", socket.gethostname()),
        help="Manufacturer shown for each input in Music Assistant (default: host name)",
    )
    parser.add_argument("--adapter", default=env("BT_ADAPTER", "hci0"))
    parser.add_argument(
        "--codec", default=env("SENDSPIN_CODEC", "pcm"), choices=["pcm", "flac", "opus"],
        help="Codec for the stream to Music Assistant",
    )
    parser.add_argument("--data-dir", type=Path, default=Path(env("DATA_DIR", "data")))
    parser.add_argument("--web-host", default=env("WEB_HOST", "0.0.0.0"))
    parser.add_argument("--web-port", type=int, default=int(env("WEB_PORT", "8080")))
    parser.add_argument(
        "--pairing-seconds", type=float, default=float(env("BT_PAIRING_SECONDS", "120"))
    )
    parser.add_argument(
        "--ma-url", default=env("MA_URL"),
        help="Music Assistant URL for speaker control, e.g. http://ma:8095",
    )
    parser.add_argument(
        "--ma-token", default=env("MA_TOKEN"), help="Long-lived Music Assistant API token"
    )
    parser.add_argument(
        "--bundled-pipewire", action=argparse.BooleanOptionalAction,
        default=env("BUNDLED_PIPEWIRE", "0") == "1",
        help="Start PipeWire + WirePlumber ourselves (the container image does this)",
    )
    parser.add_argument("--log-level", default=env("LOG_LEVEL", "INFO"))
    return parser.parse_args()


async def _run(args: argparse.Namespace) -> None:
    audio = AudioStack() if args.bundled_pipewire else None
    if audio:
        await audio.start()
    bus = await MessageBus(bus_type=BusType.SYSTEM).connect()

    bluetooth = BluetoothManager(
        bus, args.adapter, alias=args.bt_name, on_change=lambda: receivers.notify()
    )
    receivers = Receivers(
        bluetooth, args.data_dir, args.url, AudioCodec(args.codec), args.name, args.manufacturer
    )
    await bluetooth.start()
    await receivers.sync()

    ma = MusicAssistant(args.ma_url, args.ma_token) if args.ma_url and args.ma_token else None
    if ma is None:
        logger.info("MA_URL/MA_TOKEN not set; speaker control disabled")

    runner = web.AppRunner(create_app(bluetooth, receivers, args.pairing_seconds, ma))
    await runner.setup()
    await web.TCPSite(runner, args.web_host, args.web_port).start()
    logger.info("Web UI on http://%s:%d/", args.web_host, args.web_port)

    # We run as PID 1 in the container, where SIGTERM has no default action.
    stop = asyncio.Event()
    asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, stop.set)
    stop_task = asyncio.create_task(stop.wait())
    tasks = [
        stop_task,
        asyncio.create_task(bluetooth.lost.wait()),
        asyncio.create_task(receivers.failed.wait()),
    ]
    if audio:
        tasks.append(asyncio.create_task(audio.exited.wait()))
    ma_task = asyncio.create_task(ma.run()) if ma else None
    if ma_task:
        # Speaker control is optional: log a crash instead of taking the service down.
        ma_task.add_done_callback(
            lambda t: t.cancelled() or t.exception() is None
            or logger.error("Music Assistant API client crashed", exc_info=t.exception())
        )
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        if stop_task.done():
            logger.info("Stopping")
        else:
            raise SystemExit(
                "Bluetooth stack lost, PipeWire exited or a receiver failed; exiting to restart"
            )
    finally:
        for task in tasks:
            task.cancel()
        if ma_task:
            ma_task.cancel()
            await asyncio.gather(ma_task, return_exceptions=True)
        await receivers.close()
        await runner.cleanup()
        bus.disconnect()
        if audio:
            await audio.stop()


def main() -> None:
    args = _parse_args()
    logging.basicConfig(
        level=args.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        asyncio.run(_run(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
