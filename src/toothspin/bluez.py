"""BlueZ adapter control: pairing window, paired-device list, pairing agent.

Phones pair "Just Works" (no PIN) but only while the pairing window is open;
the window closes once a device has paired.

Paired phones may connect by themselves, like to any Bluetooth speaker.
Without ``allow_phone_connect``, connections are only ever started from here:
paired phones stay *untrusted*, so BlueZ asks our agent before it accepts a
phone's own profile connections, and the agent only allows them while the
pairing window is open or after ``connect_device()`` — until that connection
ends.
"""

# No ``from __future__ import annotations``: dbus-fast reads the agent's
# method annotations as D-Bus signatures.

import asyncio
import contextlib
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from dbus_fast import Message, MessageType, Variant
from dbus_fast.aio import MessageBus
from dbus_fast.errors import DBusError
from dbus_fast.service import ServiceInterface, method

from . import dbus

logger = logging.getLogger(__name__)

BLUEZ = "org.bluez"
# After a Connect, how long to watch for a phone that plays but not to us,
# and how long it has to do so (see _check_routing).
ROUTING_CHECK_S = 15.0
ROUTING_STUCK_S = 3.0
ROUTING_POLL_S = 0.5
# Pause between disconnecting and reconnecting such a phone, per attempt:
# reconnected within a second or so, Android stays stuck the same way.
ROUTING_RECONNECT_GAPS_S = (5.0, 10.0)
ADAPTER = "org.bluez.Adapter1"
DEVICE = "org.bluez.Device1"
PLAYER = "org.bluez.MediaPlayer1"
TRANSPORT = "org.bluez.MediaTransport1"
AGENT_PATH = "/org/toothspin/agent"


@dataclass(frozen=True, slots=True)
class BluetoothDevice:
    address: str
    name: str
    paired: bool
    trusted: bool
    connected: bool


@dataclass(frozen=True, slots=True)
class Transport:
    """A phone's A2DP stream as BlueZ sees it."""

    path: str
    state: str
    """idle, pending or active (streaming)."""
    volume: int | None
    """The phone's absolute volume, 0-127; None if the phone doesn't support it."""


@dataclass(frozen=True, slots=True)
class NowPlaying:
    """What the phone reports over AVRCP."""

    status: str
    title: str | None
    artist: str | None
    album: str | None
    duration_ms: int | None
    position_ms: int | None


class BluetoothManager:
    def __init__(
        self,
        bus: MessageBus,
        adapter: str = "hci0",
        alias: str | None = None,
        on_change: Callable[[], None] | None = None,
        allow_phone_connect: bool = True,
        pin: str | None = None,
    ) -> None:
        self._bus = bus
        self._adapter_path = f"/org/bluez/{adapter}"
        self._alias = alias
        self._on_change = on_change or (lambda: None)
        self._allow_phone_connect = allow_phone_connect
        # A fixed PIN is the secret for pairing, any time; see pin_pairing.
        self.pin = pin
        self._adapter: dict[str, Any] = {}
        self._devices: dict[str, dict[str, Any]] = {}
        # AVRCP players, keyed by object path (below their device's path).
        self._players: dict[str, dict[str, Any]] = {}
        # A2DP transports (the phones' streams), keyed by object path.
        self._transports: dict[str, dict[str, Any]] = {}
        self._pairing_deadline: float | None = None
        self._pairing_close: asyncio.TimerHandle | None = None
        # Device paths whose current connection we started (or that just paired).
        self._connect_allowed: set[str] = set()
        # Routing check per phone address, and phones being reconnected by it.
        self._routing_tasks: dict[str, asyncio.Task[None]] = {}
        self._reconnecting: set[str] = set()
        # Set when the adapter vanishes (dongle reset/unplug) or bluetoothd
        # restarts: our agent and adapter settings are gone, so the service
        # exits and systemd restarts it once the adapter is back.
        self.lost = asyncio.Event()

    async def start(self) -> None:
        self._bus.add_message_handler(self._on_message)
        await dbus.add_match(
            self._bus,
            f"type='signal',sender='{BLUEZ}',interface='{dbus.PROPERTIES}',"
            f"member='PropertiesChanged',path_namespace='{self._adapter_path}'",
        )
        await dbus.add_match(
            self._bus,
            f"type='signal',sender='{BLUEZ}',interface='{dbus.OBJECT_MANAGER}'",
        )
        await dbus.add_match(
            self._bus,
            "type='signal',sender='org.freedesktop.DBus',member='NameOwnerChanged',"
            f"arg0='{BLUEZ}'",
        )
        await self._reload()

        self._bus.export(AGENT_PATH, _Agent(self))
        manager = "org.bluez.AgentManager1"
        await dbus.call(
            self._bus, BLUEZ, "/org/bluez", manager, "RegisterAgent", "os",
            [AGENT_PATH, "NoInputNoOutput"],
        )
        await dbus.call(
            self._bus, BLUEZ, "/org/bluez", manager, "RequestDefaultAgent", "o", [AGENT_PATH]
        )

        await self._untrust_all()
        await self._set_adapter("Powered", Variant("b", True))
        if self._alias:
            await self._set_adapter("Alias", Variant("s", self._alias))
        await self.close_pairing()

    async def _reload(self) -> None:
        objects = await dbus.managed_objects(self._bus, BLUEZ, "/")
        if ADAPTER not in objects.get(self._adapter_path, {}):
            raise RuntimeError(f"Bluetooth adapter {self._adapter_path} not found")
        self._adapter = objects[self._adapter_path][ADAPTER]
        self._devices = {
            path: ifaces[DEVICE]
            for path, ifaces in objects.items()
            if DEVICE in ifaces and path.startswith(self._adapter_path + "/")
        }
        self._transports = {
            path: ifaces[TRANSPORT]
            for path, ifaces in objects.items()
            if TRANSPORT in ifaces and path.startswith(self._adapter_path + "/")
        }
        self._players = {
            path: _unwrap_player(ifaces[PLAYER])
            for path, ifaces in objects.items()
            if PLAYER in ifaces and path.startswith(self._adapter_path + "/")
        }

    # --- state ---

    @property
    def alias(self) -> str:
        return self._adapter.get("Alias", "")

    @property
    def address(self) -> str:
        return self._adapter.get("Address", "")

    @property
    def pairing_remaining(self) -> float | None:
        """Seconds left in the pairing window, or ``None`` when closed."""
        if self._pairing_deadline is None:
            return None
        return max(0.0, self._pairing_deadline - asyncio.get_running_loop().time())

    def devices(self) -> list[BluetoothDevice]:
        """Paired devices, connected ones first."""
        devices = [
            BluetoothDevice(
                address=props.get("Address", ""),
                name=props.get("Alias") or props.get("Name") or props.get("Address", ""),
                paired=bool(props.get("Paired")),
                trusted=bool(props.get("Trusted")),
                connected=bool(props.get("Connected")),
            )
            for props in self._devices.values()
            if props.get("Paired")
        ]
        return sorted(devices, key=lambda d: (not d.connected, d.name.lower()))

    def device_name(self, path: str) -> str | None:
        props = self._devices.get(path)
        if props is None:
            return None
        return props.get("Alias") or props.get("Name") or props.get("Address")

    def transport(self, address: str) -> Transport | None:
        """The A2DP stream of the phone with this address, if one exists."""
        device = f"{self._adapter_path}/dev_{address.upper().replace(':', '_')}/"
        for path, props in self._transports.items():
            if path.startswith(device):
                return Transport(path, props.get("State", ""), props.get("Volume"))
        return None

    async def set_phone_volume(self, transport_path: str, level: int) -> None:
        """Tell the phone its new absolute volume (0-127) over AVRCP."""
        await dbus.set_property(
            self._bus, BLUEZ, transport_path, TRANSPORT, "Volume",
            Variant("q", max(0, min(127, level))),
        )

    def now_playing(self, address: str) -> NowPlaying | None:
        """AVRCP track info for the device with this address, if it has a player."""
        device = f"{self._adapter_path}/dev_{address.upper().replace(':', '_')}/"
        for path, props in self._players.items():
            if path.startswith(device):
                track = props.get("Track") or {}
                return NowPlaying(
                    status=props.get("Status", ""),
                    title=track.get("Title") or None,
                    artist=track.get("Artist") or None,
                    album=track.get("Album") or None,
                    duration_ms=track.get("Duration"),
                    position_ms=props.get("Position"),
                )
        return None

    def owns(self, device_path: str) -> bool:
        """Whether the device belongs to our adapter (the agent is host-wide)."""
        return device_path.startswith(self._adapter_path + "/")

    def connection_allowed(self, path: str) -> bool:
        return (
            self._allow_phone_connect
            or path in self._connect_allowed
            or self.pairing_remaining is not None
        )

    # --- actions ---

    async def open_pairing(self, duration: float = 120.0) -> None:
        loop = asyncio.get_running_loop()
        self._pairing_deadline = loop.time() + duration
        if self._pairing_close is not None:
            self._pairing_close.cancel()
        self._pairing_close = loop.call_later(
            duration, lambda: asyncio.ensure_future(self.close_pairing())
        )
        await self._set_adapter("Pairable", Variant("b", True))
        await self._set_adapter("Discoverable", Variant("b", True))
        logger.info("Bluetooth pairing window open for %.0fs", duration)
        self._on_change()

    @property
    def pin_pairing(self) -> bool:
        """Phones may pair any time, with the PIN (legacy PIN pairing).

        Phones only ask for a PIN when the adapter has Secure Simple Pairing
        off (``btmgmt ssp off`` on the host, see deploy/bluetooth). With SSP
        on, they pair "Just Works", which still needs the pairing window.
        """
        return self.pin is not None

    async def close_pairing(self) -> None:
        if self._pairing_close is not None:
            self._pairing_close.cancel()
            self._pairing_close = None
        was_open = self._pairing_deadline is not None
        self._pairing_deadline = None
        # With a PIN, the adapter stays visible: the PIN guards pairing.
        await self._set_adapter("Discoverable", Variant("b", self.pin_pairing))
        await self._set_adapter("Pairable", Variant("b", self.pin_pairing))
        if was_open:
            logger.info("Bluetooth pairing window closed")
        self._on_change()

    async def remove_device(self, address: str) -> None:
        path = self._path_for(address)
        await dbus.call(self._bus, BLUEZ, self._adapter_path, ADAPTER, "RemoveDevice", "o", [path])
        logger.info("Removed Bluetooth device %s", address)

    def reconnecting(self, address: str) -> bool:
        """Being reconnected to move its audio over (see _check_routing)."""
        return address.upper() in self._reconnecting

    async def connect_device(self, address: str, *, routing_attempt: int = 0) -> None:
        """Connect a paired phone; its connections are accepted until it disconnects."""
        address = address.upper()
        path = self._path_for(address)
        if routing_attempt == 0:
            # Pressing Connect wins over an automatic reconnect still to come.
            pending = self._routing_tasks.get(address)
            if pending is not None and pending is not asyncio.current_task():
                pending.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await pending
        self._connect_allowed.add(path)
        try:
            try:
                await asyncio.wait_for(
                    dbus.call(self._bus, BLUEZ, path, DEVICE, "Connect"), timeout=30
                )
            except DBusError as err:
                # A connection attempt is already running (e.g. an automatic
                # reconnect we just cancelled): wait for its outcome instead.
                if err.type != "org.bluez.Error.InProgress":
                    raise
                await self._wait_connected(path, timeout=30)
        except (DBusError, TimeoutError):
            if not self._devices.get(path, {}).get("Connected"):
                self._connect_allowed.discard(path)
            raise
        logger.info("Connected %s", self.device_name(path))
        if routing_attempt < len(ROUTING_RECONNECT_GAPS_S):
            task = asyncio.create_task(
                self._check_routing(address, routing_attempt), name=f"routing {address}"
            )
            self._routing_tasks[address] = task
            task.add_done_callback(
                lambda t: self._routing_tasks.get(address) is t
                and self._routing_tasks.pop(address)
            )

    async def _wait_connected(self, path: str, timeout: float) -> None:
        async with asyncio.timeout(timeout):
            while not self._devices.get(path, {}).get("Connected"):
                await asyncio.sleep(0.25)

    async def _check_routing(self, address: str, attempt: int) -> None:
        """Reconnect if the phone plays, but not to us.

        Right after a connection Android sometimes keeps playing on its own
        speaker: it reports "playing" over AVRCP, but never starts the A2DP
        stream. A fresh connection, a few seconds later, makes it switch; only
        shortly after the user pressed Connect, so a later choice of other
        headphones stands, and at most twice.
        """
        loop = asyncio.get_running_loop()
        deadline = loop.time() + ROUTING_CHECK_S
        playing_since: float | None = None
        while loop.time() < deadline:
            await asyncio.sleep(ROUTING_POLL_S)
            transport = self.transport(address)
            if transport is not None and transport.state in ("pending", "active"):
                return  # streaming to us
            now_playing = self.now_playing(address)
            if now_playing is None or now_playing.status != "playing":
                playing_since = None
                continue
            playing_since = playing_since or loop.time()
            if loop.time() - playing_since >= ROUTING_STUCK_S:
                break
        else:
            return
        path = self._path_for(address)
        name = self.device_name(path)
        gap = ROUTING_RECONNECT_GAPS_S[attempt]
        logger.warning(
            "%s plays, but not over Bluetooth; reconnecting it in %.0fs", name, gap
        )
        self._reconnecting.add(address)
        self._on_change()
        try:
            await self.disconnect_device(address)
            # Wait until it's really gone, then give the phone time to settle.
            for _ in range(20):
                if not self._devices.get(path, {}).get("Connected"):
                    break
                await asyncio.sleep(0.5)
            await asyncio.sleep(gap)
            await self.connect_device(address, routing_attempt=attempt + 1)
        except (DBusError, TimeoutError, KeyError) as err:
            logger.warning("Reconnecting %s failed: %s", name, err or "timed out")
        finally:
            self._reconnecting.discard(address)
            self._on_change()

    async def refuse(self, path: str) -> None:
        """Disconnect a phone that connected on its own."""
        if self.connection_allowed(path):
            return
        logger.info("Disconnecting %s: connections start from the receiver", self.device_name(path))
        try:
            await dbus.call(self._bus, BLUEZ, path, DEVICE, "Disconnect")
        except DBusError as err:
            logger.warning("Could not disconnect %s: %s", path, err)

    async def _untrust_all(self) -> None:
        """Phones paired before this policy were trusted, which bypasses the agent."""
        for path, props in self._devices.items():
            if props.get("Trusted") and not self._allow_phone_connect:
                await dbus.set_property(
                    self._bus, BLUEZ, path, DEVICE, "Trusted", Variant("b", False)
                )
                logger.info("Untrusted %s: connections now start from here", props.get("Alias"))
            if props.get("Connected"):
                # Keep an existing connection alive across a service restart.
                self._connect_allowed.add(path)

    async def disconnect_device(self, address: str) -> None:
        await dbus.call(self._bus, BLUEZ, self._path_for(address), DEVICE, "Disconnect")

    def _path_for(self, address: str) -> str:
        for path, props in self._devices.items():
            if props.get("Address", "").upper() == address.upper():
                return path
        raise KeyError(address)

    async def _set_adapter(self, name: str, value: Variant) -> None:
        await dbus.set_property(self._bus, BLUEZ, self._adapter_path, ADAPTER, name, value)

    # --- signals ---

    def _on_message(self, msg: Message) -> None:
        if msg.message_type is not MessageType.SIGNAL or not msg.path:
            return
        if msg.member == "NameOwnerChanged" and msg.body and msg.body[0] == BLUEZ:
            logger.error("bluetoothd went away")
            self.lost.set()
        elif msg.member == "PropertiesChanged" and msg.interface == dbus.PROPERTIES:
            iface, changed, _invalidated = msg.body
            if iface == ADAPTER and msg.path == self._adapter_path:
                self._adapter.update(dbus.unwrap(changed))
                self._on_change()
            elif iface == DEVICE and msg.path in self._devices:
                changed = dbus.unwrap(changed)
                self._devices[msg.path].update(changed)
                if changed.get("Paired"):
                    asyncio.ensure_future(self._on_paired(msg.path))
                if changed.get("Connected") is False:
                    self._connect_allowed.discard(msg.path)
                elif changed.get("Connected") and not self.connection_allowed(msg.path):
                    # Only some profiles (A2DP) ask the agent; the link itself and
                    # AVRCP don't. Drop connections we didn't start.
                    asyncio.ensure_future(self.refuse(msg.path))
                self._on_change()
            elif iface == PLAYER and msg.path in self._players:
                self._players[msg.path].update(_unwrap_player(changed))
            elif iface == TRANSPORT and msg.path in self._transports:
                # A phone starting its stream (capture picks it up at once) or
                # changing its volume.
                self._transports[msg.path].update(dbus.unwrap(changed))
                self._on_change()
        elif msg.member == "InterfacesAdded" and msg.interface == dbus.OBJECT_MANAGER:
            path, ifaces = msg.body
            if DEVICE in ifaces and path.startswith(self._adapter_path + "/"):
                self._devices[path] = dbus.unwrap(ifaces[DEVICE])
                self._on_change()
            if PLAYER in ifaces and path.startswith(self._adapter_path + "/"):
                self._players[path] = _unwrap_player(ifaces[PLAYER])
            if TRANSPORT in ifaces and path.startswith(self._adapter_path + "/"):
                self._transports[path] = dbus.unwrap(ifaces[TRANSPORT])
                self._on_change()
        elif msg.member == "InterfacesRemoved" and msg.interface == dbus.OBJECT_MANAGER:
            path, ifaces = msg.body
            if path == self._adapter_path and ADAPTER in ifaces:
                logger.error("Bluetooth adapter %s went away", path)
                self.lost.set()
            elif DEVICE in ifaces and self._devices.pop(path, None) is not None:
                self._on_change()
            if PLAYER in ifaces:
                self._players.pop(path, None)
            if TRANSPORT in ifaces and self._transports.pop(path, None) is not None:
                self._on_change()

    async def _on_paired(self, path: str) -> None:
        logger.info("Paired with %s", self.device_name(path))
        # Let the phone finish the connection it paired over.
        self._connect_allowed.add(path)
        if self._pairing_deadline is not None:
            await self.close_pairing()


def _unwrap_player(props: dict[str, Variant]) -> dict[str, Any]:
    """Unwrap MediaPlayer1 properties, including the nested Track dict."""
    unwrapped = dbus.unwrap(props)
    if isinstance(unwrapped.get("Track"), dict):
        unwrapped["Track"] = dbus.unwrap(unwrapped["Track"])
    return unwrapped


class _Agent(ServiceInterface):
    """Accepts pairing only while the window is open, and connections we started.

    BlueZ's default agent serves every adapter on the host. Devices on other
    adapters (e.g. the one Home Assistant uses for its own Bluetooth devices)
    are left alone: they're accepted, as BlueZ does when no agent is
    registered, so pairings the host starts there keep working.
    """

    def __init__(self, manager: BluetoothManager) -> None:
        super().__init__("org.bluez.Agent1")
        self._manager = manager

    def _require_window(self, device: str) -> None:
        if not self._manager.owns(device):
            return
        if self._manager.pairing_remaining is None:
            logger.warning("Rejected pairing from %s: pairing window closed", device)
            raise DBusError("org.bluez.Error.Rejected", "Pairing window closed")

    @method()
    def Release(self):  # noqa: N802
        pass

    @method()
    def RequestPinCode(self, device: "o") -> "s":  # noqa: F821, N802
        if self._manager.owns(device) and self._manager.pin is not None:
            # Legacy PIN pairing: the phone's user must type the same PIN.
            logger.info("Answering PIN request from %s", device)
            return self._manager.pin
        self._require_window(device)
        return "0000"

    @method()
    def DisplayPinCode(self, device: "o", pincode: "s"):  # noqa: F821, N802
        self._require_window(device)

    @method()
    def RequestPasskey(self, device: "o") -> "u":  # noqa: F821, N802
        self._require_window(device)
        return 0

    @method()
    def DisplayPasskey(self, device: "o", passkey: "u", entered: "q"):  # noqa: F821, N802
        pass

    @method()
    def RequestConfirmation(self, device: "o", passkey: "u"):  # noqa: F821, N802
        self._require_window(device)

    @method()
    def RequestAuthorization(self, device: "o"):  # noqa: F821, N802
        self._require_window(device)

    @method()
    def AuthorizeService(self, device: "o", uuid: "s"):  # noqa: F821, N802
        if self._manager.owns(device) and not self._manager.connection_allowed(device):
            logger.info("Rejected connection from %s: not started from here", device)
            asyncio.ensure_future(self._manager.refuse(device))
            raise DBusError("org.bluez.Error.Rejected", "Connect from the receiver")

    @method()
    def Cancel(self):  # noqa: N802
        pass
