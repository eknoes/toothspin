"""Bluetooth A2DP receiver feeding Music Assistant as a Sendspin source."""

import os
from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("toothspin")
except PackageNotFoundError:  # running from a checkout without installing
    __version__ = "dev"


def build_info() -> dict[str, str | None]:
    """Version and the commit the image was built from (GIT_COMMIT at build time)."""
    commit = os.environ.get("TOOTHSPIN_COMMIT", "")
    sha, _, dirty = commit.partition("-")
    return {"version": __version__, "commit": (sha[:7] + ("-" + dirty if dirty else "")) or None}
