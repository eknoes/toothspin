"""Entry point: wire BlueZ, PipeWire capture, the Sendspin source and the web UI."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import re
import signal
import socket
from pathlib import Path

import aiohttp
from aiohttp import web
from aiosendspin.models.types import AudioCodec
from dbus_fast import BusType
from dbus_fast.aio import MessageBus
from dbus_fast.errors import DBusError

from . import ha, ma_pairing, setup_check
from .audio_stack import AudioStack
from .bluez import BluetoothManager
from .ma import MusicAssistant, check_version, probe_version
from .receivers import Receivers
from .volume_sync import DEFAULT_START_VOLUME, VolumeSync
from .web import create_app, create_setup_app

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
        "--bt-name", default=env("BT_NAME", "ToothSpin"),
        help="Bluetooth name phones see",
    )
    parser.add_argument(
        "--manufacturer", default=env("SENDSPIN_MANUFACTURER", socket.gethostname()),
        help="Manufacturer shown for each input in Music Assistant (default: host name)",
    )
    parser.add_argument(
        "--adapter", default=env("BT_ADAPTER", "hci0"),
        help="hci0, hci1, ... or auto: one Home Assistant doesn't use (as an App), else the first",
    )
    parser.add_argument(
        "--codec", default=env("SENDSPIN_CODEC", "pcm"), choices=["pcm", "flac", "opus"],
        help="Codec for the stream to Music Assistant",
    )
    parser.add_argument("--data-dir", type=Path, default=Path(env("DATA_DIR", "data")))
    parser.add_argument("--web-host", default=env("WEB_HOST", "0.0.0.0"))
    parser.add_argument("--web-port", type=int, default=int(env("WEB_PORT", "8080")))
    parser.add_argument(
        "--lan-port", type=int, default=int(env("LAN_PORT")) if env("LAN_PORT") else None,
        help="As a Home Assistant App: also serve the web UI on this port to the LAN",
    )
    parser.add_argument(
        "--start-volume", type=int, default=int(env("START_VOLUME", str(DEFAULT_START_VOLUME))),
        help="The loudest a speaker starts at when a phone starts playing on it (0-100)",
    )
    parser.add_argument(
        "--allow-phone-connect", action=argparse.BooleanOptionalAction,
        default=_flag(env("ALLOW_PHONE_CONNECT", "true")),
        help="Accept connections phones start themselves (default); without, only the web UI's Connect",
    )
    parser.add_argument(
        "--bt-pin", default=env("BT_PIN"),
        help="Let phones pair any time with this PIN (6-16 digits; needs SSP off on the host)",
    )
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
    args = parser.parse_args()
    args.start_volume = max(0, min(100, args.start_volume))
    if args.bt_pin is not None and not re.fullmatch(r"\d{6,16}", args.bt_pin):
        # Legacy PIN pairing has no retry limit: short PINs can be guessed.
        raise SystemExit("BT_PIN must be 6 to 16 digits")
    return args


def _flag(value: str) -> bool:
    return value.strip().lower() in ("1", "true", "yes", "on")


SETUP_NOTIFICATION = "toothspin_setup"
FAQ_URL = "https://eknoes.github.io/toothspin/faq.html"
# How often to look again while setup is blocked, and while running.
RECHECK_S = 15.0
WATCH_S = 60.0
MA_VERSION_S = 1800.0


class _Web:
    """The web UI on its ports: first the setup page, then the real thing."""

    def __init__(self, host: str, ports: list[int], ingress_port: int | None) -> None:
        self._host = host
        self._ports = ports
        self._ingress_port = ingress_port
        self._runner: web.AppRunner | None = None

    async def serve(self, app: web.Application) -> None:
        if self._runner is not None:
            await self._runner.cleanup()
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        for port in self._ports:
            await web.TCPSite(self._runner, self._host, port).start()

    def log_addresses(self) -> None:
        for port in self._ports:
            label = "ingress" if port == self._ingress_port else "web UI"
            logger.info("Serving %s on http://%s:%d/", label, self._host, port)

    async def close(self) -> None:
        if self._runner is not None:
            await self._runner.cleanup()


async def _check_adapter(bus: MessageBus, configured: str, app: bool) -> setup_check.Result:
    try:
        found = await setup_check.adapters(bus)
    except DBusError:
        return setup_check.Result(None, setup_check.bluetooth_missing())
    usage = None
    if app:
        try:
            usage = await ha.bluetooth_adapter_usage()
        except (aiohttp.ClientError, OSError, RuntimeError, TimeoutError) as err:
            logger.warning("Couldn't ask Home Assistant which Bluetooth adapters it uses: %s", err)
    return setup_check.choose(configured, found, usage)


async def _report(
    status: setup_check.Status, problem: setup_check.Problem | None, shown: list[str | None]
) -> None:
    """Log a new problem, and tell Home Assistant if it blocks; clear it once gone.

    Warnings (ToothSpin works, but could work better) only go to the log
    and the web UI, not as a notification on every start.
    """
    title = problem.title if problem else None
    previous, shown[0] = shown[0], title
    if title == previous:
        return
    if problem is not None:
        log = logger.error if problem.fatal else logger.warning
        log("%s. %s", problem.title, problem.as_markdown().replace("**", "").replace("`", ""))
    else:
        logger.info("Solved: %s", previous)
    if not status.app:
        return
    try:
        if problem is None or not problem.fatal:
            await ha.dismiss(SETUP_NOTIFICATION)
        else:
            await ha.notify(
                SETUP_NOTIFICATION,
                f"ToothSpin: {problem.title}",
                problem.as_markdown(status.app_slug) + "\n\nDetails: open ToothSpin from the sidebar. "
                f"Help: [FAQ]({FAQ_URL}).",
            )
    except (aiohttp.ClientError, OSError) as err:
        logger.warning("Couldn't update the notification in Home Assistant: %s", err)


async def _claim_adapter(
    bus: MessageBus, configured: str, status: setup_check.Status, shown: list[str | None]
) -> setup_check.Adapter:
    """Wait until there's an adapter ToothSpin may use; explain why not meanwhile."""
    while True:
        result = await _check_adapter(bus, configured, status.app)
        if result.adapter is not None:
            status.problem = None
            status.adapter = result.adapter
            status.warning = result.problem
            await _report(status, result.problem, shown)
            return result.adapter
        status.problem = result.problem
        await _report(status, result.problem, shown)
        await asyncio.sleep(RECHECK_S)


async def _watch_adapter(
    bus: MessageBus, configured: str, status: setup_check.Status, shown: list[str | None]
) -> None:
    """While running: warn if Home Assistant takes over (or offers to) our adapter."""
    while True:
        await asyncio.sleep(WATCH_S)
        assert status.adapter is not None
        result = await _check_adapter(bus, status.adapter.name, status.app)
        status.warning = result.problem
        await _report(status, result.problem, shown)


async def _watch_ma_version(url: str | None, status: setup_check.Status) -> None:
    """Without a token: look up Music Assistant's version now and then (it may update)."""
    while True:
        version = await probe_version(url)
        if version and version != status.ma_version:
            status.ma_version = version
            logger.info("Music Assistant %s", version)
            check_version(version)
        await asyncio.sleep(MA_VERSION_S)


async def _run(args: argparse.Namespace) -> None:
    status = setup_check.Status(app=ha.running_as_app(), ma_token=bool(args.ma_token))
    ingress_port = None
    if status.app:
        ingress_port, status.app_slug = await ha.app_info()
    if ingress_port:
        ports = [ingress_port] + ([args.lan_port] if args.lan_port else [])
    else:
        ports = [args.web_port]
    site = _Web(args.web_host, ports, ingress_port)
    # Up first, so problems before Bluetooth starts can be shown there.
    await site.serve(create_setup_app(status, ingress_port))
    site.log_addresses()
    if status.app:
        try:
            await ha.show_in_sidebar()
        except (aiohttp.ClientError, OSError) as err:
            logger.warning("Couldn't add ToothSpin to the sidebar: %s", err)

    audio = AudioStack() if args.bundled_pipewire else None
    if audio:
        await audio.start()
    bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
    shown: list[str | None] = [None]
    adapter = await _claim_adapter(bus, args.adapter, status, shown)
    logger.info("Using Bluetooth adapter %s", adapter.label)

    def on_bluetooth_change() -> None:
        receivers.notify()
        if volume_sync:
            volume_sync.notify()

    volume_sync: VolumeSync | None = None
    bluetooth = BluetoothManager(
        bus, adapter.name, alias=args.bt_name, on_change=on_bluetooth_change,
        allow_phone_connect=args.allow_phone_connect, pin=args.bt_pin or None,
    )
    # Without MA_URL the API is found via mDNS, so in HA only the token is needed.
    ma = MusicAssistant(args.ma_url, args.ma_token) if args.ma_token else None
    if ma is None:
        logger.info("MA_TOKEN not set; speaker control and automatic pairing disabled")
    receivers = Receivers(
        bluetooth, args.data_dir, args.url, AudioCodec(args.codec), args.name,
        args.manufacturer,
        # With API access, ToothSpin pairs each input with MA itself.
        alongside=(lambda source: ma_pairing.keep_paired(ma, source)) if ma else None,
        pin_pairing=ma is None,
        on_forget=(lambda client_id: ma_pairing.remove(ma, client_id)) if ma else None,
    )
    await bluetooth.start()
    await receivers.sync()

    await site.serve(
        create_app(
            bluetooth, receivers, args.pairing_seconds, ma, ingress_port=ingress_port,
            start_volume=args.start_volume, auto_pairing=ma is not None, status=status,
        )
    )

    # We run as PID 1 in the container, where SIGTERM has no default action.
    stop = asyncio.Event()
    asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, stop.set)
    stop_task = asyncio.create_task(stop.wait())
    tasks = [
        stop_task,
        asyncio.create_task(bluetooth.lost.wait()),
        asyncio.create_task(receivers.failed.wait()),
    ]
    watch = asyncio.create_task(_watch_adapter(bus, adapter.name, status, shown))
    # With a token, the API connection reports Music Assistant's version.
    version_watch = None if ma else asyncio.create_task(_watch_ma_version(args.ma_url, status))
    if audio:
        tasks.append(asyncio.create_task(audio.exited.wait()))
    ma_task = asyncio.create_task(ma.run()) if ma else None
    if ma:
        volume_sync = VolumeSync(bluetooth, receivers, ma, args.start_volume)
        tasks.append(asyncio.create_task(volume_sync.run()))
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
        watch.cancel()
        if version_watch:
            version_watch.cancel()
        await receivers.close()
        await site.close()
        bus.disconnect()
        if audio:
            await audio.stop()


def main() -> None:
    as_app = ha.apply_options()
    args = _parse_args()
    logging.basicConfig(
        level=args.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if as_app:
        logger.info("Running as a Home Assistant App")
    try:
        asyncio.run(_run(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
