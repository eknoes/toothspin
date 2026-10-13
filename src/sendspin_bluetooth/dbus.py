"""Thin helpers over dbus-fast's low-level message API."""

from __future__ import annotations

from typing import Any

from dbus_fast import Message, MessageType, Variant
from dbus_fast.aio import MessageBus
from dbus_fast.errors import DBusError

PROPERTIES = "org.freedesktop.DBus.Properties"
OBJECT_MANAGER = "org.freedesktop.DBus.ObjectManager"


async def call(
    bus: MessageBus,
    destination: str,
    path: str,
    interface: str,
    member: str,
    signature: str = "",
    body: list[Any] | None = None,
) -> Message:
    """Call a method and return the reply, raising ``DBusError`` on an error reply."""
    reply = await bus.call(
        Message(
            destination=destination,
            path=path,
            interface=interface,
            member=member,
            signature=signature,
            body=body or [],
        )
    )
    assert reply is not None
    if reply.message_type is MessageType.ERROR:
        raise DBusError(reply.error_name or "unknown", reply.body[0] if reply.body else "")
    return reply


async def set_property(
    bus: MessageBus, destination: str, path: str, interface: str, name: str, value: Variant
) -> None:
    await call(bus, destination, path, PROPERTIES, "Set", "ssv", [interface, name, value])


async def add_match(bus: MessageBus, rule: str) -> None:
    await call(
        bus,
        "org.freedesktop.DBus",
        "/org/freedesktop/DBus",
        "org.freedesktop.DBus",
        "AddMatch",
        "s",
        [rule],
    )


async def managed_objects(
    bus: MessageBus, destination: str, path: str
) -> dict[str, dict[str, dict[str, Any]]]:
    """Return ``GetManagedObjects`` with property variants unwrapped."""
    reply = await call(bus, destination, path, OBJECT_MANAGER, "GetManagedObjects")
    return {
        obj: {iface: unwrap(props) for iface, props in ifaces.items()}
        for obj, ifaces in reply.body[0].items()
    }


def unwrap(props: dict[str, Variant]) -> dict[str, Any]:
    return {key: value.value for key, value in props.items()}
