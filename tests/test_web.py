import asyncio
import json
from urllib.parse import urljoin

from aiohttp.test_utils import TestClient, TestServer

from toothspin.web import create_app


def test_serves_pwa_files() -> None:
    async def scenario() -> None:
        app = create_app(bluetooth=None, receivers=None, pairing_seconds=120)  # type: ignore[arg-type]
        async with TestClient(TestServer(app)) as client:
            index = await (await client.get("/")).text()
            assert 'rel="manifest"' in index

            manifest = json.loads(await (await client.get("/static/manifest.webmanifest")).text())
            assert manifest["display"] == "standalone"
            for icon in manifest["icons"]:
                # Relative to the manifest, as browsers resolve them.
                res = await client.get(urljoin("/static/manifest.webmanifest", icon["src"]))
                assert res.status == 200 and res.content_type.startswith("image/")

            sw = await client.get("/sw.js")
            assert sw.status == 200 and sw.content_type == "application/javascript"

    asyncio.run(scenario())


def test_posts_from_other_sites_are_refused() -> None:
    async def scenario() -> None:
        app = create_app(bluetooth=None, receivers=None, pairing_seconds=120)  # type: ignore[arg-type]
        async with TestClient(TestServer(app)) as client:
            # What a form or a no-cors fetch on another website can send.
            for content_type in ("text/plain", "application/x-www-form-urlencoded"):
                res = await client.post(
                    "/api/bluetooth/pairing", data='{"open": true}',
                    headers={"Content-Type": content_type},
                )
                assert res.status == 415

    asyncio.run(scenario())
