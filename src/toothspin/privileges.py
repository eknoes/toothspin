"""Run as an unprivileged user instead of root.

ToothSpin uses the host's system D-Bus. Services there (systemd, for one)
decide by the caller's user ID, not its capabilities: as root, ToothSpin
could ask them for anything, as any other user nothing they guard. BlueZ
talks to any user. Started as root (a Home Assistant App, plain Docker),
ToothSpin hands its files to the image's own user and switches to it;
started as a user already (rootless Podman), there's nothing to do.
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


def _chown_tree(root: Path, uid: int, gid: int) -> None:
    if not root.exists():
        return
    for path in [root, *root.rglob("*")]:
        if path.lstat().st_uid != uid:
            os.lchown(path, uid, gid)
