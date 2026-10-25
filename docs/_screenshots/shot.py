"""Screenshots and a demo GIF of the web UI, rendered with demo state.

Serves src/toothspin/index.html with a fake receiver behind /api: it starts
from demo.json and applies the web UI's requests (speakers on/off, moves,
volume, mute), so no real devices, names or covers end up in the docs. From
the repo root:

    podman run --rm -v .:/repo:Z mcr.microsoft.com/playwright/python:v1.52.0-noble \\
        sh -c "apt-get -qq update && apt-get -qq install -y ffmpeg >/dev/null \\
               && pip install -q playwright==1.52.0 && python /repo/docs/_screenshots/shot.py"

Set CHROMIUM to a browser binary to use that instead of Playwright's own.
"""

import copy
import json
import mimetypes
import os
import pathlib
import shutil
import subprocess
import re
import tempfile
from urllib.parse import unquote

from playwright.sync_api import sync_playwright

here = pathlib.Path(__file__).parent
repo = here.parents[1]
site = repo / "src" / "toothspin"
out = repo / "docs" / "assets" / "screenshots"
demo = json.loads((here / "demo.json").read_text())
demo["about"] = {
    "version": re.search(r'^version = "(.+)"', (repo / "pyproject.toml").read_text(), re.M)[1],
    "commit": None,
}
PHONE = "AA:BB:CC:00:00:01"

TOKEN = {
    "kind": "todo", "title": "Add a Music Assistant token",
    "text": "To pick speakers here, pair phones with Music Assistant by themselves, "
    "and control the speakers with the phone's volume buttons.",
    "steps": [
        "In Music Assistant, click your profile (bottom left) → **Tokens** → "
        "**Create token**, and copy it.",
        "Paste it as **Music Assistant token** in [ToothSpin's configuration](ha:app-config), "
        "save and restart ToothSpin.",
    ],
}
OFFERED = {
    "kind": "todo", "title": "Let Home Assistant ignore ToothSpin's adapter",
    "text": "Home Assistant found ToothSpin's adapter (00:1A:7D:DA:71:13) and offers to add "
    "it to its Bluetooth integration. ToothSpin works best when Home Assistant leaves it alone.",
    "steps": [
        "Press **Ignore in Home Assistant**, or in [Settings → Devices & services]"
        "(ha:integrations) choose **Ignore** on the discovered *Bluetooth* entry for "
        "00:1A:7D:DA:71:13.",
    ],
    "action": "ignore-adapter",
}
BLOCKED = {
    "title": "No Bluetooth adapter found",
    "text": "ToothSpin needs a Bluetooth adapter, but this system has none, or "
    "Bluetooth isn't running on it.",
    "steps": [
        "Plug a USB Bluetooth dongle into this machine (for a virtual machine: pass "
        "the USB device through to it).",
        "If it's plugged in, restart the machine so it's detected.",
    ],
}


class Receiver:
    """Just enough of ToothSpin's API for the web UI to work."""

    def __init__(self, setup=None):
        self.state = copy.deepcopy(demo)
        self.state["setup"] = setup or {"problem": None, "todo": [], "app": True, "app_slug": "demo_toothspin"}

    def speakers(self):
        return {s["player_id"]: s for s in self.state["speakers"]["list"]}

    def uri(self, address):
        return next(d["source_uri"] for d in self.state["devices"] if d["address"] == address)

    def play(self, uri, player_id, on):
        spk = self.speakers()
        playing = [s for s in spk.values() if s["playing_uri"] == uri]
        leader = next((s for s in playing if not s["synced_to"]), None)
        s = spk[player_id]
        if on:
            s["playing_uri"], s["synced_to"] = uri, leader["player_id"] if leader else None
        else:
            s["playing_uri"] = s["synced_to"] = None
            if leader is s:  # hand the group to the next one
                rest = [x for x in playing if x is not s]
                for i, x in enumerate(rest):
                    x["synced_to"] = None if i == 0 else rest[0]["player_id"]

    def handle(self, route):
        req = route.request
        path = req.url.split("toothspin.test", 1)[1].split("?")[0]
        body = json.loads(req.post_data) if req.method == "POST" and req.post_data else {}
        parts = [unquote(part) for part in path.strip("/").split("/")]
        if path == "/api/state":
            return route.fulfill(body=json.dumps(self.state), content_type="application/json")
        if parts[:2] == ["api", "speakers"] and parts[2:] == ["volume"]:
            s = self.speakers()[body["player_id"]]
            if "muted" in body:
                s["muted"] = body["muted"]
            else:
                s["volume"] = body["volume"]
        elif parts[:2] == ["api", "speakers"] and parts[3] == "toggle":
            self.play(self.uri(parts[2]), body["player_id"], body["on"])
        elif parts[:2] == ["api", "speakers"] and parts[3] == "move":
            uri = self.uri(parts[2])
            for s in self.speakers().values():
                if s["playing_uri"] == uri:
                    s["playing_uri"] = s["synced_to"] = None
            self.play(uri, body["player_id"], True)
        elif parts[:2] == ["api", "devices"] and parts[3:] == ["cover"]:
            return route.fulfill(path=here / "cover.svg", content_type="image/svg+xml")
        elif path == "/":
            return route.fulfill(path=site / "index.html", content_type="text/html")
        elif path.startswith("/static/") and (site / path.lstrip("/")).is_file():
            f = site / path.lstrip("/")
            return route.fulfill(path=f, content_type=mimetypes.guess_type(f.name)[0] or "application/octet-stream")
        elif not path.startswith("/api/"):
            return route.fulfill(status=404, body="")
        route.fulfill(body='{"ok": true}', content_type="application/json")


def open_page(browser, receiver, scheme="light", width=640, height=800, setup_open=False, **kwargs):
    page = browser.new_page(viewport={"width": width, "height": height}, color_scheme=scheme, **kwargs)
    page.add_init_script(f'localStorage.setItem("myPhone", "{PHONE}");'
                         f'localStorage.setItem("setupOpen", "{1 if setup_open else 0}")')
    page.on("pageerror", lambda e: print("pageerror", e))
    page.route("**/*", receiver.handle)
    page.goto("http://toothspin.test/")
    page.wait_for_timeout(2000)
    return page


def screenshots(browser):
    for scheme in ("dark", "light"):
        page = open_page(browser, Receiver(), scheme, device_scale_factor=2)
        page.screenshot(path=out / f"web-ui-{scheme}.png", full_page=True)
    for name, todo, opened in (("setup", [OFFERED, TOKEN], True), ("setup-collapsed", [OFFERED, TOKEN], False)):
        setup = {"problem": None, "todo": todo, "app": True, "app_slug": "demo_toothspin"}
        page = open_page(browser, Receiver(setup), "light", width=480, setup_open=opened, device_scale_factor=2)
        page.locator("#setup").screenshot(path=out / f"{name}.png")
    setup = {"problem": BLOCKED, "todo": [], "app": True, "app_slug": "demo_toothspin"}
    page = open_page(browser, Receiver(setup), "light", width=480, device_scale_factor=2)
    page.locator("main").screenshot(path=out / "setup-blocked.png")


def demo_gif(browser):
    """Add a speaker to the group, set its volume, then play only there.

    Built from sharp 2x screenshots rather than a video recording, which
    Playwright only does at 1x.
    """
    width = 480
    page = open_page(browser, Receiver(), "light", width=width, height=900, device_scale_factor=2)
    frames: list[tuple[bytes, float]] = []
    # Header and the first phone's card, down to its buttons.
    bottom = page.locator(f'button[data-action="disconnect"]').bounding_box()
    clip = {"x": 0, "y": 0, "width": width, "height": bottom["y"] + bottom["height"] + 18}

    def frame(seconds):
        frames.append((page.screenshot(clip=clip), seconds))

    def finger(x=None, y=None):
        """Show where the finger touches (x, y), like a phone does; no x: lift it."""
        page.evaluate("""([x, y]) => {
            let dot = document.getElementById("finger");
            if (!dot) {
                dot = document.createElement("div");
                dot.id = "finger";
                dot.style.cssText = "position: fixed; z-index: 9999; pointer-events: none; "
                    + "width: 36px; height: 36px; margin: -18px 0 0 -18px; border-radius: 50%; "
                    + "background: rgba(15, 27, 45, 0.3); border: 2px solid rgba(255, 255, 255, 0.9);";
                document.documentElement.append(dot);  // outside what the UI re-renders
            }
            dot.hidden = x === null;
            if (x !== null) { dot.style.left = `${x}px`; dot.style.top = `${y}px`; }
        }""", [x, y])

    def tap(selector, before=0.5, after=1.4):
        box = page.locator(selector).bounding_box()
        finger(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        frame(before)
        page.click(selector)
        page.wait_for_timeout(150)
        frame(0.3)
        finger()
        frame(after)

    card = f'[data-addr="{PHONE}"]'
    frame(1.4)
    tap(f'button[data-speaker="office"]{card}')
    slider = page.locator('input[data-vol="office"]')
    slider.wait_for(state="visible")
    page.wait_for_timeout(300)  # the next poll re-renders the card
    box = slider.bounding_box()
    y = box["y"] + box["height"] / 2
    x = box["x"] + box["width"] * 0.2
    page.mouse.move(x, y)
    finger(x, y)
    frame(0.4)
    page.mouse.down()
    for i in range(1, 13):
        x = box["x"] + box["width"] * (0.2 + i * 0.04)
        page.mouse.move(x, y)
        finger(x, y)
        frame(0.06)
    page.mouse.up()
    page.wait_for_timeout(150)
    frame(0.3)
    finger()
    frame(1.2)
    tap(f'button[data-move="office"]{card}', after=2.4)

    with tempfile.TemporaryDirectory() as tmp:
        tmp = pathlib.Path(tmp)
        lines = []
        for n, (png, seconds) in enumerate(frames):
            (tmp / f"{n:03}.png").write_bytes(png)
            lines += [f"file '{n:03}.png'", f"duration {seconds}"]
        lines.append(f"file '{len(frames) - 1:03}.png'")  # concat needs the last one twice
        (tmp / "frames.txt").write_text("\n".join(lines) + "\n")
        scale = f"scale={width}:-1:flags=lanczos"
        concat = ["-f", "concat", "-safe", "0", "-i", tmp / "frames.txt"]
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", *concat, "-vf",
                        f"{scale},palettegen=stats_mode=full", tmp / "palette.png"], check=True)
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", *concat, "-i", tmp / "palette.png",
                        "-lavfi", f"{scale} [x]; [x][1:v] paletteuse=dither=none", out / "demo.gif"],
                       check=True)


with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=os.environ.get("CHROMIUM"))
    screenshots(browser)
    if shutil.which("ffmpeg"):
        demo_gif(browser)
    else:
        print("ffmpeg missing: skipping demo.gif")
    browser.close()
