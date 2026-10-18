"""Entry point: wire BlueZ, PipeWire capture, the Sendspin source and the web UI."""

from __future__ import annotations

import argparse
import asyncio
import errno
import json
import logging
import os
import re
import signal
import socket
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

import aiohttp
from aiohttp import web
from aiosendspin.models.types import AudioCodec
from dbus_fast import BusType
from dbus_fast.aio import MessageBus
from dbus_fast.errors import DBusError

from . import audio_stack, ha, ha_audio, ma_pairing, privileges, setup_check
from .audio_stack import AudioStack
from .bluez import BluetoothManager, NowPlaying
from .backend import PlayerBackend
from .ma import MusicAssistant, check_version, probe_version
from .receivers import Receivers
from .volume_sync import DEFAULT_START_VOLUME, VolumeSync
from .web import create_app, create_setup_app

if TYPE_CHECKING:
    from .server import ToothSpinServer

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
    # All interfaces: the web UI is for the home network. Behind Home
    # Assistant's ingress, its port only answers the Supervisor's proxy.
    parser.add_argument("--web-host", default=env("WEB_HOST", "0.0.0.0"))  # noqa: S104
    parser.add_argument("--web-port", type=int, default=int(env("WEB_PORT", "8080")))
    parser.add_argument(
        "--mode", choices=["music-assistant", "standalone"],
        default=env("MODE", "music-assistant"),
        help="Feed Music Assistant, or run ToothSpin's own Sendspin server for Sendspin speakers",
    )
    parser.add_argument(
        "--server-port", type=int, default=int(env("SERVER_PORT", "8927")),
        help="Standalone mode: port of ToothSpin's Sendspin server",
    )
    parser.add_argument(
        "--speaker-buffer-ms", type=int, default=_optional_int(env("SPEAKER_BUFFER_MS")),
        help="Standalone mode: buffer (ms) for speakers that don't report their own "
        "(default: 1000). Less starts playback sooner, too little drops out",
    )
    parser.add_argument(
        "--start-volume", type=int, default=int(env("START_VOLUME", str(DEFAULT_START_VOLUME))),
        help="The loudest a speaker starts at when a phone starts playing on it (0-100)",
    )
    parser.add_argument(
        "--take-bluetooth-audio", action=argparse.BooleanOptionalAction,
        default=_flag(env("TAKE_BLUETOOTH_AUDIO", "false")),
        help="As a Home Assistant App: turn off Bluetooth in Home Assistant's audio service",
    )
    parser.add_argument(
        "--allow-phone-connect", action=argparse.BooleanOptionalAction,
        default=_flag(env("ALLOW_PHONE_CONNECT", "true")),
        help="Accept connections phones start themselves (default); without, only the web UI's Connect",
    )
    parser.add_argument(
        "--other-adapters-pairing", default=env("OTHER_ADAPTERS_PAIRING", "accept"),
        choices=["accept", "refuse"],
        help="Pairings on the host's other Bluetooth adapters, which BlueZ asks ToothSpin about",
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
    if args.speaker_buffer_ms is not None and not 100 <= args.speaker_buffer_ms <= 5000:
        raise SystemExit("SPEAKER_BUFFER_MS must be 100 to 5000")
    if args.bt_pin is not None and not re.fullmatch(r"\d{6,16}", args.bt_pin):
        # Legacy PIN pairing has no retry limit: short PINs can be guessed.
        raise SystemExit("BT_PIN must be 6 to 16 digits")
    return args


def _optional_int(value: str | None) -> int | None:
    return int(value) if value else None


def _flag(value: str) -> bool:
    return value.strip().lower() in ("1", "true", "yes", "on")


SETUP_NOTIFICATION = "toothspin_setup"
FAQ_URL = "https://eknoes.github.io/toothspin/faq.html"
# How often to look again while setup is blocked, and while running.
RECHECK_S = 15.0
WATCH_S = 60.0
MA_VERSION_S = 1800.0
AUDIO_S = 20.0
RECONNECT_FILE = "reconnect.json"
# Let BlueZ see ToothSpin's audio endpoints before reconnecting.
RECONNECT_DELAY_S = 3.0


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


async def _take_bluetooth_audio(bluetooth: BluetoothManager, status: setup_check.Status) -> None:
    """Turn off Bluetooth in Home Assistant's audio service; reconnect the phones it held."""
    held = await ha_audio.release()
    status.audio_conflict = None
    logger.info("Turned off Bluetooth in Home Assistant's audio service")
    ours = {d.address for d in bluetooth.devices() if d.connected}
    for address in held:
        if address not in ours:
            continue
        # Its stream sits in Home Assistant's audio service: a new connection
        # negotiates it with ToothSpin.
        logger.info("Reconnecting %s so its audio reaches ToothSpin", address)
        try:
            await bluetooth.disconnect_device(address)
            await asyncio.sleep(2)
            await bluetooth.connect_device(address)
        except (DBusError, TimeoutError) as err:
            logger.warning("Reconnecting %s failed: %s", address, err)


async def _watch_ha_audio(bluetooth: BluetoothManager, status: setup_check.Status) -> None:
    """Keep Home Assistant's audio service off Bluetooth if the user agreed, else ask.

    It loads its Bluetooth modules again whenever it restarts (e.g. after an update).
    """
    failing = False
    while True:
        try:
            if await ha_audio.bluetooth_modules():
                if status.take_bluetooth_audio:
                    await _take_bluetooth_audio(bluetooth, status)
                elif status.audio_conflict is None:
                    status.audio_conflict = setup_check.ha_audio_takes_bluetooth()
                    logger.warning(
                        "Home Assistant's audio service also receives Bluetooth audio and "
                        "takes the phones' streams. Allow ToothSpin to turn that off in "
                        "its web UI (Finish setup)."
                    )
            else:
                status.audio_conflict = None
            failing = False
        except ha_audio.AudioServiceError as err:
            if not failing:
                logger.warning("Couldn't check Home Assistant's audio service: %s", err)
            failing = True
        await asyncio.sleep(AUDIO_S)


def _remember_connected(bluetooth: BluetoothManager, path: Path) -> None:
    connected = [d.address for d in bluetooth.devices() if d.connected]
    try:
        path.write_text(json.dumps(connected))
    except OSError as err:
        logger.warning("Couldn't remember the connected phones: %s", err)


async def _reconnect_after_restart(bluetooth: BluetoothManager, path: Path) -> None:
    """Reconnect the phones that were connected when ToothSpin last stopped.

    A restart (an update, a changed option) drops them: BlueZ ends their
    audio connection once ToothSpin's audio stack is gone.
    """
    try:
        addresses = json.loads(path.read_text())
        path.unlink()
    except (OSError, ValueError):
        return
    await asyncio.sleep(RECONNECT_DELAY_S)
    for device in bluetooth.devices():
        if device.address in addresses and not device.connected:
            logger.info("Reconnecting %s after the restart", device.name)
            try:
                await bluetooth.connect_device(device.address)
            except (DBusError, TimeoutError) as err:
                logger.warning("Reconnecting %s failed: %s", device.name, err)


async def _watch_ma_version(url: str | None, status: setup_check.Status) -> None:
    """Without a token: look up Music Assistant's version now and then (it may update)."""
    while True:
        version = await probe_version(url)
        if version and version != status.ma_version:
            status.ma_version = version
            logger.info("Music Assistant %s", version)
            check_version(version)
        await asyncio.sleep(MA_VERSION_S)


async def _start_server(
    args: argparse.Namespace, now_playing: Callable[[str], NowPlaying | None]
) -> ToothSpinServer:
    try:
        from . import server as server_module
        from .server import ToothSpinServer
    except ImportError as err:
        raise SystemExit(
            f"Standalone mode needs the toothspin-standalone image: {err}"
        ) from err
    server = ToothSpinServer(
        args.data_dir, "ToothSpin", args.server_port, speaker_buffer_ms=args.speaker_buffer_ms,
        now_playing=now_playing,
    )
    server_module.watch_sendspin_logs(server.note_late)
    try:
        await server.start()
    except OSError as err:
        if err.errno != errno.EADDRINUSE:
            raise
        raise SystemExit(
            f"Port {args.server_port} is already in use, most likely by Music Assistant's "
            "Sendspin server. Standalone mode can't run next to it: use ToothSpin with "
            "Music Assistant instead (MODE=music-assistant, or the ToothSpin App)."
        ) from err
    return server


async def _run(args: argparse.Namespace) -> None:
    status = setup_check.Status(
        app=ha.running_as_app(),
        # Standalone has no Music Assistant to need a token for.
        ma_token=bool(args.ma_token) or args.mode == "standalone",
        take_bluetooth_audio=args.take_bluetooth_audio,
    )
    ingress_port = None
    lan = False
    if status.app:
        ingress_port, status.app_slug, lan = await ha.app_info()
        # No host network, so no mDNS: Music Assistant's App runs on the host.
        if not args.ma_url:
            args.ma_url = f"http://{ha.HOST_IP}:8095"
        if not args.url:
            args.url = f"ws://{ha.HOST_IP}:8927/sendspin"
    if ingress_port:
        ports = [ingress_port] + ([ha.LAN_PORT] if lan else [])
    else:
        ports = [args.web_port]
    site = _Web(args.web_host, ports, ingress_port)
    # Up first, so problems before Bluetooth starts can be shown there.
    await site.serve(create_setup_app(status, ingress_port, args.mode))
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
        other_adapters_pairing=args.other_adapters_pairing == "accept",
    )
    backend: PlayerBackend | None
    if args.mode == "standalone":
        # Our own Sendspin server: the phones' sources connect to it, paired
        # automatically, and it plays them on Sendspin speakers.
        def now_playing(source_id: str) -> NowPlaying | None:
            """What the phone behind this Sendspin source plays, for the speakers."""
            for device in bluetooth.devices():
                receiver = receivers.get(device.address)
                if receiver is not None and receiver.source.client.identity.peer_id == source_id:
                    return bluetooth.now_playing(device.address)
            return None

        server = await _start_server(args, now_playing)
        backend = server
        receivers = Receivers(
            bluetooth, args.data_dir, server.url, AudioCodec(args.codec), args.name,
            args.manufacturer, prepare_source=server.pair_local, pin_pairing=False,
            on_forget=server.forget,
        )
    else:
        # Without MA_URL the API is found via mDNS, so in HA only the token is needed.
        ma = MusicAssistant(args.ma_url, args.ma_token) if args.ma_token else None
        backend = ma
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
    reconnect_file = args.data_dir / RECONNECT_FILE
    reconnect = asyncio.create_task(_reconnect_after_restart(bluetooth, reconnect_file))

    await site.serve(
        create_app(
            bluetooth, receivers, args.pairing_seconds, backend, ingress_port=ingress_port,
            start_volume=args.start_volume, mode=args.mode,
            auto_pairing=args.mode == "music-assistant" and backend is not None,
            status=status,
            take_bluetooth_audio=(lambda: _take_bluetooth_audio(bluetooth, status))
            if ha_audio.available() else None,
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
    version_watch = (
        asyncio.create_task(_watch_ma_version(args.ma_url, status))
        if args.mode == "music-assistant" and backend is None else None
    )
    audio_watch = (
        asyncio.create_task(_watch_ha_audio(bluetooth, status))
        if status.app and ha_audio.available() else None
    )
    if audio:
        tasks.append(asyncio.create_task(audio.exited.wait()))
    backend_task = asyncio.create_task(backend.run()) if backend else None
    if backend:
        volume_sync = VolumeSync(bluetooth, receivers, backend, args.start_volume)
        tasks.append(asyncio.create_task(volume_sync.run()))
    if backend_task and args.mode == "standalone":
        # Without its own server, ToothSpin has nothing to play on.
        tasks.append(backend_task)
    elif backend_task:
        # Speaker control is optional: log a crash instead of taking the service down.
        backend_task.add_done_callback(
            lambda t: t.cancelled() or t.exception() is None
            or logger.error("Music Assistant API client crashed", exc_info=t.exception())
        )
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        if stop_task.done():
            logger.info("Stopping")
        else:
            raise SystemExit(
                "Bluetooth stack lost, PipeWire or the Sendspin server exited, or a receiver "
                "failed; exiting to restart"
            )
    finally:
        # Our audio stack going away drops the phones; reconnect them next start.
        _remember_connected(bluetooth, reconnect_file)
        reconnect.cancel()
        for task in tasks:
            task.cancel()
        watch.cancel()
        for task in (version_watch, audio_watch):
            if task:
                task.cancel()
        # Sources say goodbye before our own server (if any) goes away.
        await receivers.close()
        if backend_task:
            backend_task.cancel()
            await asyncio.gather(backend_task, return_exceptions=True)
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
    runtime = Path(os.environ.get("XDG_RUNTIME_DIR", audio_stack.DEFAULT_RUNTIME))
    privileges.drop_root(args.data_dir, runtime)
    try:
        asyncio.run(_run(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
