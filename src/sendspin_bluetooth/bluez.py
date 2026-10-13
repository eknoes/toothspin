"""BlueZ adapter control: pairing window, paired-device list, pairing agent.

Phones pair "Just Works" (no PIN) but only while the pairing window is open;
the first device that pairs in a window is trusted and the window closes.
"""

# No ``from __future__ import annotations``: dbus-fast reads the agent's
# method annotations as D-Bus signatures.

import asyncio
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
ADAPTER = "org.bluez.Adapter1"
DEVICE = "org.bluez.Device1"
PLAYER = "org.bluez.MediaPlayer1"
AGENT_PATH = "/org/sendspin/bluetooth/agent"


@dataclass(frozen=True, slots=True)
class BluetoothDevice:
    address: str
    name: str
    paired: bool
    trusted: bool
    connected: bool


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
    ) -> None:
        self._bus = bus
        self._adapter_path = f"/org/bluez/{adapter}"
        self._alias = alias
        self._on_change = on_change or (lambda: None)
        self._adapter: dict[str, Any] = {}
        self._devices: dict[str, dict[str, Any]] = {}
        # AVRCP players, keyed by object path (below their device's path).
        self._players: dict[str, dict[str, Any]] = {}
        self._pairing_deadline: float | None = None
        self._pairing_close: asyncio.TimerHandle | None = None
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

    def _is_trusted(self, path: str) -> bool:
        return bool(self._devices.get(path, {}).get("Trusted"))

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

    async def close_pairing(self) -> None:
        if self._pairing_close is not None:
            self._pairing_close.cancel()
            self._pairing_close = None
        was_open = self._pairing_deadline is not None
        self._pairing_deadline = None
        await self._set_adapter("Discoverable", Variant("b", False))
        await self._set_adapter("Pairable", Variant("b", False))
        if was_open:
            logger.info("Bluetooth pairing window closed")
        self._on_change()

    async def remove_device(self, address: str) -> None:
        path = self._path_for(address)
        await dbus.call(self._bus, BLUEZ, self._adapter_path, ADAPTER, "RemoveDevice", "o", [path])
        logger.info("Removed Bluetooth device %s", address)

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
                self._on_change()
            elif iface == PLAYER and msg.path in self._players:
                self._players[msg.path].update(_unwrap_player(changed))
            elif iface == "org.bluez.MediaTransport1":
                # A phone starting its stream: lets capture pick it up at once.
                self._on_change()
        elif msg.member == "InterfacesAdded" and msg.interface == dbus.OBJECT_MANAGER:
            path, ifaces = msg.body
            if DEVICE in ifaces and path.startswith(self._adapter_path + "/"):
                self._devices[path] = dbus.unwrap(ifaces[DEVICE])
                self._on_change()
            if PLAYER in ifaces and path.startswith(self._adapter_path + "/"):
                self._players[path] = _unwrap_player(ifaces[PLAYER])
        elif msg.member == "InterfacesRemoved" and msg.interface == dbus.OBJECT_MANAGER:
            path, ifaces = msg.body
            if path == self._adapter_path and ADAPTER in ifaces:
                logger.error("Bluetooth adapter %s went away", path)
                self.lost.set()
            elif DEVICE in ifaces and self._devices.pop(path, None) is not None:
                self._on_change()
            if PLAYER in ifaces:
                self._players.pop(path, None)

    async def _on_paired(self, path: str) -> None:
        logger.info("Paired with %s; trusting it", self.device_name(path))
        try:
            await dbus.set_property(self._bus, BLUEZ, path, DEVICE, "Trusted", Variant("b", True))
        except DBusError:
            logger.exception("Could not trust %s", path)
        if self._pairing_deadline is not None:
            await self.close_pairing()


def _unwrap_player(props: dict[str, Variant]) -> dict[str, Any]:
    """Unwrap MediaPlayer1 properties, including the nested Track dict."""
    unwrapped = dbus.unwrap(props)
    if isinstance(unwrapped.get("Track"), dict):
        unwrapped["Track"] = dbus.unwrap(unwrapped["Track"])
    return unwrapped


class _Agent(ServiceInterface):
    """Accepts pairing only while the window is open; services only for trusted devices."""

    def __init__(self, manager: BluetoothManager) -> None:
        super().__init__("org.bluez.Agent1")
        self._manager = manager

    def _require_window(self, device: str) -> None:
        if self._manager.pairing_remaining is None:
            logger.warning("Rejected pairing from %s: pairing window closed", device)
            raise DBusError("org.bluez.Error.Rejected", "Pairing window closed")

    @method()
    def Release(self):  # noqa: N802
        pass

    @method()
    def RequestPinCode(self, device: "o") -> "s":  # noqa: F821, N802
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
        if not self._manager._is_trusted(device):  # noqa: SLF001
            self._require_window(device)

    @method()
    def Cancel(self):  # noqa: N802
        pass
