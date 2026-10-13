"""Entry point: wire BlueZ, bluealsa, the Sendspin source and the web UI."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
from pathlib import Path

from aiohttp import web
from aiosendspin.models.types import AudioCodec
from dbus_fast import BusType
from dbus_fast.aio import MessageBus

from .bluez import BluetoothManager
from .capture import Capture
from .source import SendspinSource
from .web import create_app

logger = logging.getLogger(__name__)


def _parse_args() -> argparse.Namespace:
    env = os.environ.get
    parser = argparse.ArgumentParser(prog="sendspin-bluetooth", description=__doc__)
    parser.add_argument(
        "--url", default=env("SENDSPIN_URL"),
        help="Sendspin server URL, e.g. ws://ma:8927/sendspin (default: discover via mDNS)",
    )
    parser.add_argument(
        "--name", default=env("SENDSPIN_NAME", "Bluetooth"),
        help="Name of this source in Music Assistant",
    )
    parser.add_argument(
        "--bt-name", default=env("BT_NAME", "Music Assistant"),
        help="Bluetooth name phones see",
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
    parser.add_argument("--log-level", default=env("LOG_LEVEL", "INFO"))
    return parser.parse_args()


async def _run(args: argparse.Namespace) -> None:
    bus = await MessageBus(bus_type=BusType.SYSTEM).connect()

    source = SendspinSource(args.name, args.url, args.data_dir, AudioCodec(args.codec))
    await source.setup()

    capture = Capture(source, source.client.now_us)

    bluetooth = BluetoothManager(bus, args.adapter, alias=args.bt_name, on_change=capture.notify)
    await bluetooth.start()

    runner = web.AppRunner(create_app(bluetooth, source, capture, args.pairing_seconds))
    await runner.setup()
    await web.TCPSite(runner, args.web_host, args.web_port).start()
    logger.info("Web UI on http://%s:%d/", args.web_host, args.web_port)

    tasks = [
        asyncio.create_task(source.run()),
        asyncio.create_task(capture.run()),
        asyncio.create_task(bluetooth.lost.wait()),
    ]
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
        raise SystemExit("Bluetooth stack lost; exiting so the service restarts")
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await runner.cleanup()
        bus.disconnect()


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
