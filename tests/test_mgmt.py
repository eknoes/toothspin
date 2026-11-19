import socket
import struct

import pytest

from toothspin import mgmt


def _event(code: int, index: int, params: bytes) -> bytes:
    return struct.pack("<HHH", code, index, len(params)) + params


def _reply(index: int, status: int, code: int = mgmt.EVENT_COMMAND_COMPLETE) -> bytes:
    params = struct.pack("<HB", mgmt.OP_SET_DEV_CLASS, status)
    return _event(code, index, params + (b"\x14\x04\x00" if status == 0 else b""))


@pytest.fixture
def pair():
    ours, kernel = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
    yield ours, kernel
    ours.close()
    kernel.close()


def test_command_bytes() -> None:
    assert mgmt.set_dev_class_command(1, 0x04, 0x14) == bytes.fromhex("0e00 0100 0200 0414")


def test_parse_event() -> None:
    assert mgmt.parse_event(_event(1, 2, b"abc") + b"junk") == (1, 2, b"abc")
    with pytest.raises(mgmt.MgmtError):
        mgmt.parse_event(b"\x01")


def test_adapter_index() -> None:
    assert mgmt.adapter_index("/org/bluez/hci12") == 12


def test_success_skips_unrelated_events(pair) -> None:
    ours, kernel = pair
    kernel.send(_event(0x0006, 0, b"\x00"))  # some other event
    kernel.send(_reply(1, 0))  # reply for another controller
    kernel.send(_reply(0, 0))
    mgmt.set_dev_class(ours, 0)
    assert kernel.recv(64) == mgmt.set_dev_class_command(0, 0x04, 0x14)


def test_permission_denied(pair) -> None:
    ours, kernel = pair
    kernel.send(_reply(0, 0x14, mgmt.EVENT_COMMAND_STATUS))
    with pytest.raises(mgmt.MgmtError, match="permission denied"):
        mgmt.set_dev_class(ours, 0)


def test_timeout(pair) -> None:
    ours, _ = pair
    with pytest.raises(mgmt.MgmtError, match="no reply"):
        mgmt.set_dev_class(ours, 0, timeout=0.05)


def test_apply_class_never_raises(pair, caplog) -> None:
    ours, kernel = pair
    kernel.send(_reply(0, 0x14, mgmt.EVENT_COMMAND_STATUS))
    mgmt.apply_class(ours, "/org/bluez/hci0", as_app=True)
    assert "permission denied" in caplog.text
    assert ours.fileno() == -1  # closed
    caplog.clear()
    mgmt.apply_class(None, "/org/bluez/hci0", as_app=False)
    assert not caplog.text
