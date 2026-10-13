"""Screenshots of the web UI for the Pages site, rendered with demo state.

Serves src/toothspin/index.html and its static files with demo.json as
/api/state, so no real devices or names end up on the site. From the repo
root:

    podman run --rm -v .:/repo:Z mcr.microsoft.com/playwright/python:v1.52.0-noble \
        sh -c "pip install -q playwright==1.52.0 && python /repo/docs/_screenshots/shot.py"
"""

import mimetypes
import pathlib

from playwright.sync_api import sync_playwright

here = pathlib.Path(__file__).parent
repo = here.parents[1]
site = repo / "src" / "toothspin"
out = repo / "docs" / "assets" / "screenshots"
demo = (here / "demo.json").read_text()


def handle(route):
    path = route.request.url.split("toothspin.test", 1)[1].split("?")[0]
    if path == "/api/state":
        return route.fulfill(body=demo, content_type="application/json")
    if path == "/":
        return route.fulfill(path=site / "index.html", content_type="text/html")
    if path.startswith("/static/"):
        f = site / path.lstrip("/")
        if f.is_file():
            return route.fulfill(path=f, content_type=mimetypes.guess_type(f.name)[0] or "application/octet-stream")
    route.fulfill(status=404, body="")


with sync_playwright() as p:
    browser = p.chromium.launch()
    for scheme in ("dark", "light"):
        page = browser.new_page(viewport={"width": 640, "height": 800}, color_scheme=scheme, device_scale_factor=2)
        page.add_init_script('localStorage.setItem("myPhone", "AA:BB:CC:00:00:01")')
        page.on("pageerror", lambda e: print("pageerror", e))
        page.route("**/*", handle)
        page.goto("http://toothspin.test/")
        page.wait_for_timeout(2500)
        page.screenshot(path=out / f"web-ui-{scheme}.png", full_page=True)
    browser.close()
