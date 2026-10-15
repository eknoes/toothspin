"""Before Bluetooth starts: is there an adapter ToothSpin may have to itself?

ToothSpin takes over its Bluetooth adapter (name, visibility, pairing,
connections). Home Assistant's Bluetooth integration only scans for
Bluetooth Low Energy devices, so the two can share an adapter, but a dongle
of its own is more reliable. As a Home Assistant App, ToothSpin asks HA which
adapters its integration uses and warns when it shares one; elsewhere it can
only check that the adapter exists.

Problems are written for people, not developers: what's wrong, why it
matters, and exactly what to do.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from dbus_fast.aio import MessageBus

from . import dbus, ha

AUTO = "auto"
ADAPTER = "org.bluez.Adapter1"
# Links in problem texts are written [label](ha:page); the web UI, the
# notification and the log each turn them into what works there.
HA_PAGES = {
    "integrations": "/config/integrations/dashboard",
    "bluetooth": "/config/integrations/integration/bluetooth",
    "app-config": "/config/app/{slug}/config",
}
_HA_LINK = re.compile(r"\[([^\]]+)\]\(ha:([a-z-]+)\)")


@dataclass(slots=True)
class Adapter:
    name: str
    """hci0, hci1, ..."""
    address: str
    alias: str

    @property
    def label(self) -> str:
        return f"{self.alias} ({self.name}, {self.address})"


@dataclass(slots=True)
class Problem:
    """Something the user has to fix before ToothSpin can work (or should)."""

    title: str
    text: str
    steps: list[str] = field(default_factory=list)
    fatal: bool = True
    action: str | None = None
    """Something ToothSpin can fix itself when asked: the web UI offers a button."""

    def as_markdown(self, app_slug: str | None = None) -> str:
        """Markdown with links into Home Assistant, or plain labels without a slug."""
        steps = "\n".join(f"{n}. {step}" for n, step in enumerate(self.steps, start=1))
        text = f"{self.text}\n\n{steps}" if steps else self.text

        def link(match: re.Match[str]) -> str:
            label, page = match.groups()
            if not app_slug or page not in HA_PAGES:
                return label
            return f"[{label}]({HA_PAGES[page].format(slug=app_slug)})"

        return _HA_LINK.sub(link, text)


@dataclass(slots=True)
class Result:
    adapter: Adapter | None
    problem: Problem | None = None
    """Fatal problem (no adapter to use) or a warning next to a usable adapter."""


async def adapters(bus: MessageBus) -> list[Adapter]:
    objects = await dbus.managed_objects(bus, "org.bluez", "/")
    found = [
        Adapter(
            name=path.rsplit("/", 1)[-1],
            address=str(ifaces[ADAPTER].get("Address", "")).upper(),
            alias=str(ifaces[ADAPTER].get("Alias") or ifaces[ADAPTER].get("Name") or ""),
        )
        for path, ifaces in objects.items()
        if ADAPTER in ifaces
    ]
    return sorted(found, key=lambda a: _index(a.name))


def choose(configured: str, found: list[Adapter], usage: dict[str, str] | None) -> Result:
    """Pick the adapter to use, or explain why there's none.

    ``usage`` is Home Assistant's view (address -> ha.USED, ...), None when
    not running as an App (then nothing is known about other users).
    """
    if not found:
        return Result(None, Problem(
            "No Bluetooth adapter found",
            "ToothSpin needs a Bluetooth adapter, but this system has none, or "
            "Bluetooth isn't running on it.",
            [
                "Plug a USB Bluetooth dongle into this machine (for a virtual machine: "
                "pass the USB device through to it).",
                "If it's plugged in, restart the machine so it's detected.",
            ],
        ))
    used = {a.address for a in found if usage and usage.get(a.address) == ha.USED}

    if configured == AUTO:
        # Prefer an adapter of its own, but share one if that's all there is.
        free = [a for a in found if a.address not in used]
        adapter = (free or found)[0]
    else:
        adapter = next((a for a in found if a.name == configured), None)
        if adapter is None:
            return Result(None, Problem(
                f"Bluetooth adapter {configured} not found",
                f"The configuration names the adapter **{configured}**, but there is no "
                f"such adapter. Available: {_list(found, usage)}.",
                [
                    "Set **Bluetooth adapter** in [ToothSpin's configuration](ha:app-config) "
                    "(`BT_ADAPTER` outside Home Assistant) to one of the adapters above.",
                    "Restart ToothSpin.",
                ],
            ))
    if adapter.address in used:
        return Result(adapter, _shared(adapter))
    return Result(adapter, _offered(adapter, usage))


def _shared(adapter: Adapter) -> Problem:
    return Problem(
        "Bluetooth adapter shared with Home Assistant",
        f"Home Assistant's Bluetooth integration uses {adapter.label} too. That "
        "works, but phones may drop out or stutter. A dongle just for ToothSpin "
        "avoids that.",
        [
            "Plug in a second USB Bluetooth dongle.",
            "In [Settings → Devices & services → Bluetooth](ha:bluetooth), **ignore** "
            "the new dongle if it's under *Discovered*, or **disable** it (⋮ menu).",
            "Set **Bluetooth adapter** in [ToothSpin's configuration](ha:app-config) to "
            "the new dongle (e.g. `hci1`, or `auto`) and restart ToothSpin.",
        ],
        fatal=False,
    )


def _offered(adapter: Adapter, usage: dict[str, str] | None) -> Problem | None:
    if not usage or usage.get(adapter.address) != ha.OFFERED:
        return None
    return Problem(
        "Let Home Assistant ignore ToothSpin's adapter",
        f"Home Assistant found ToothSpin's adapter ({adapter.address}) and offers to "
        "add it. ToothSpin works best if Home Assistant leaves it alone.",
        [
            "Press **Ignore in Home Assistant**, or in [Settings → Devices & "
            "services](ha:integrations) choose **Ignore** on the discovered *Bluetooth* "
            f"entry for {adapter.address}.",
        ],
        fatal=False,
        action="ignore-adapter",
    )


def _list(found: list[Adapter], usage: dict[str, str] | None) -> str:
    def state(a: Adapter) -> str:
        return {
            ha.USED: "used by Home Assistant",
            ha.DISABLED: "disabled in Home Assistant",
            ha.IGNORED: "ignored by Home Assistant",
            ha.OFFERED: "discovered by Home Assistant, not added",
        }.get((usage or {}).get(a.address, ""), "free" if usage is not None else "")

    return "; ".join(
        f"{a.label}{f' – {state(a)}' if state(a) else ''}" for a in found
    )


def _index(name: str) -> int:
    match = re.search(r"\d+$", name)
    return int(match.group()) if match else 0


@dataclass(slots=True)
class Status:
    """What the web UI shows about setup: blocking problem, warning, checks."""

    app: bool
    """Running as a Home Assistant App."""
    ma_token: bool
    app_slug: str = ""
    """The App's slug, for links to its pages in Home Assistant."""
    ma_version: str | None = None
    """Music Assistant's version when there's no API connection to tell it."""
    take_bluetooth_audio: bool = False
    """The user agreed that ToothSpin takes Bluetooth audio from Home Assistant's
    own audio service."""
    audio_conflict: Problem | None = None
    """Home Assistant's audio service takes the phones' audio (no consent yet)."""
    adapter: Adapter | None = None
    problem: Problem | None = None
    """Blocks ToothSpin from starting: the web UI shows only this."""
    warning: Problem | None = None
    """Shown above the normal UI, e.g. HA taking over the adapter later."""


def bluetooth_missing() -> Problem:
    return Problem(
        "Bluetooth isn't running",
        "ToothSpin couldn't reach the system's Bluetooth service (BlueZ).",
        [
            "Make sure a Bluetooth adapter is connected and Bluetooth is enabled on "
            "the host.",
            "Outside Home Assistant: ToothSpin needs the host's `bluetoothd` and its "
            "D-Bus socket mounted into the container (see the README).",
        ],
    )


def ha_audio_takes_bluetooth() -> Problem:
    return Problem(
        "Let ToothSpin receive the phones' audio",
        "Home Assistant's own audio service grabs the phones' audio: they connect, "
        "but nothing plays. ToothSpin can turn that off.",
        [
            "Press **Take Bluetooth audio**. Home Assistant then can't use Bluetooth "
            "speakers or headsets itself (few setups do).",
            "To undo it, turn off **Take Bluetooth audio from Home Assistant** in "
            "[ToothSpin's configuration](ha:app-config) and restart Home Assistant.",
        ],
        fatal=False,
        action="take-bluetooth-audio",
    )

