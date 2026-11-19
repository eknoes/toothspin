"""Set the adapter's Class of Device through the kernel's management interface.

Android TV's pairing screen only lists devices whose major class is Audio/
Video; an adapter without a configured class advertises "Misc". Docker and
CoreOS installs set ``Class`` in BlueZ's main.conf, but a Home Assistant
App can't change the host's /etc/bluetooth, and BlueZ has no D-Bus API for
it (Adapter1.Class is read-only; issue #27). So we send the kernel the same
command ``btmgmt class`` does.

The management socket only accepts commands from a "trusted" socket, which
it is if the process had CAP_NET_ADMIN when binding it. Bind it before
dropping root (see privileges.py); the flag stays with the socket.
"""

from __future__ import annotations

import logging
import socket
import struct
import time

logger = logging.getLogger(__name__)

AF_BLUETOOTH = getattr(socket, "AF_BLUETOOTH", 31)
BTPROTO_HCI = getattr(socket, "BTPROTO_HCI", 1)
HCI_DEV_NONE = 0xFFFF
HCI_CHANNEL_CONTROL = 3

OP_SET_DEV_CLASS = 0x000E
EVENT_COMMAND_COMPLETE = 0x0001
EVENT_COMMAND_STATUS = 0x0002
STATUS_NAMES = {0x0A: "busy", 0x0D: "invalid parameters", 0x14: "permission denied"}

# Major class Audio/Video, minor Loudspeaker; what main.conf's 0x000414 sets.
MAJOR_AUDIO_VIDEO = 0x04
MINOR_LOUDSPEAKER = 0x14


class MgmtError(Exception):
    pass


def open_socket() -> socket.socket:
    """The management socket; call while still root (see module docstring)."""
    sock = socket.socket(AF_BLUETOOTH, socket.SOCK_RAW, BTPROTO_HCI)
    try:
        sock.bind((HCI_DEV_NONE, HCI_CHANNEL_CONTROL))
    except OSError:
        sock.close()
        raise
    return sock


def set_dev_class_command(index: int, major: int, minor: int) -> bytes:
    return struct.pack("<HHHBB", OP_SET_DEV_CLASS, index, 2, major, minor)


def parse_event(data: bytes) -> tuple[int, int, bytes]:
    """(event code, controller index, parameters) of one management event."""
    if len(data) < 6:
        raise MgmtError("short management event")
    code, index, length = struct.unpack_from("<HHH", data)
    return code, index, data[6 : 6 + length]


def set_dev_class(
    sock: socket.socket, index: int, major: int = MAJOR_AUDIO_VIDEO,
    minor: int = MINOR_LOUDSPEAKER, timeout: float = 3.0,
) -> None:
    """Send SET_DEV_CLASS and wait for its reply; raises MgmtError on failure.

    Blocking, but it only waits for the kernel; other events (e.g. from
    other controllers) are skipped until the reply to our command arrives.
    """
    deadline = time.monotonic() + timeout
    try:
        sock.settimeout(timeout)
        sock.send(set_dev_class_command(index, major, minor))
        while True:
            # One deadline, however many other events arrive meanwhile.
            sock.settimeout(max(deadline - time.monotonic(), 0.001))
            code, event_index, params = parse_event(sock.recv(1024))
            if (
                code in (EVENT_COMMAND_COMPLETE, EVENT_COMMAND_STATUS)
                and event_index == index
                and len(params) >= 3
                and struct.unpack_from("<H", params)[0] == OP_SET_DEV_CLASS
            ):
                status = params[2]
                if status:
                    name = STATUS_NAMES.get(status, f"status {status:#04x}")
                    raise MgmtError(name)
                return
    except TimeoutError as err:
        raise MgmtError("no reply from the kernel") from err
    except OSError as err:
        raise MgmtError(str(err)) from err


def adapter_index(adapter_path: str) -> int:
    """0 for /org/bluez/hci0."""
    return int(adapter_path.rsplit("hci", 1)[1])


def apply_class(sock: socket.socket | None, adapter_path: str, as_app: bool) -> None:
    """Set the class, once; never fatal.

    Without a socket (no host network or capability) or on failure, main.conf
    is what sets the class outside Home Assistant, so only the App warns.
    """
    if sock is None:
        if as_app:
            logger.warning(
                "Couldn't set the Bluetooth device class (Android TV may not list ToothSpin): "
                "the App needs host network and the NET_ADMIN capability"
            )
        return
    try:
        set_dev_class(sock, adapter_index(adapter_path))
    except (MgmtError, ValueError, IndexError) as err:
        (logger.warning if as_app else logger.debug)(
            "Couldn't set the Bluetooth device class: %s", err
        )
    else:
        logger.info("Set the Bluetooth device class to speaker")
    finally:
        sock.close()
