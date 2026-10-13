import asyncio
import json

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
                res = await client.get(icon["src"])
                assert res.status == 200 and res.content_type.startswith("image/")

            sw = await client.get("/sw.js")
            assert sw.status == 200 and sw.content_type == "application/javascript"

    asyncio.run(scenario())
