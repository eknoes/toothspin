"""Run as an unprivileged user instead of root.

ToothSpin uses the host's system D-Bus. Services there (systemd, for one)
decide by the caller's user ID, not its capabilities: as root, ToothSpin
could ask them for anything, as any other user nothing they guard. BlueZ
talks to any user. Started as root (a Home Assistant App, Docker without
``--user``), ToothSpin hands its files to the image's own user and switches
to it; started as a user already (Docker with ``--user 1000:1000``, rootless
Podman), there's nothing to do.
"""

from __future__ import annotations

import ctypes
import logging
import os
import pwd
from pathlib import Path

logger = logging.getLogger(__name__)

USER = "toothspin"
PR_SET_NO_NEW_PRIVS = 38


def drop_root(*paths: Path, user: str = USER) -> None:
    """Switch to ``user``, after handing it ``paths`` (its data and runtime files)."""
    if os.getuid() != 0:
        _require_owned(paths[0])
        return
    try:
        account = pwd.getpwnam(user)
    except KeyError:
        logger.warning("Running as root: there's no %s user in this image", user)
        return
    try:
        for path in paths:
            _chown_tree(path, account.pw_uid, account.pw_gid)
        os.setgroups([])
        os.setgid(account.pw_gid)
        os.setuid(account.pw_uid)
    except PermissionError as err:
        logger.warning(
            "Running as root: couldn't switch to the %s user (%s). Allow the "
            "CHOWN, SETUID and SETGID capabilities; ToothSpin gives them up "
            "right after.", user, err,
        )
        return
    # Nothing started from here may gain privileges again (setuid programs).
    ctypes.CDLL(None, use_errno=True).prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0)
    os.environ["HOME"] = account.pw_dir
    logger.info("Running as user %s", user)


def _require_owned(data_dir: Path) -> None:
    """Started as a user: its data must be its own, e.g. not left from a root start."""
    if not data_dir.exists():
        return
    uid = os.getuid()
    for path in [data_dir, *data_dir.rglob("*")]:
        if path.lstat().st_uid != uid:
            raise SystemExit(
                f"{path} belongs to uid {path.lstat().st_uid}, but ToothSpin runs as uid "
                f"{uid}. Hand the data over once: chown -R {uid}:{os.getgid()} on the "
                "volume or folder mounted as /data."
            )


def _chown_tree(root: Path, uid: int, gid: int) -> None:
    if root.is_symlink():
        # Root would hand over whatever the link points to.
        raise PermissionError(f"{root} is a symbolic link")
    if not root.exists():
        return
    for path in [root, *root.rglob("*")]:
        if path.lstat().st_uid != uid:
            os.lchown(path, uid, gid)
