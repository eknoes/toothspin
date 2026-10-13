import asyncio
import json
import os
import re
from importlib.resources import files

from aiohttp.test_utils import TestClient, TestServer

from toothspin import ha
from toothspin.web import create_app


def test_app_options_become_environment_defaults(tmp_path, monkeypatch) -> None:
    for env in ha.OPTION_ENV.values():
        monkeypatch.delenv(env, raising=False)
    monkeypatch.setenv("BT_NAME", "set explicitly")
    options = tmp_path / "options.json"
    options.write_text(json.dumps({
        "bluetooth_name": "from options",
        "adapter": "hci1",
        "ma_token": "secret",
        "ma_url": "",
        "lan_port": 8080,
        "log_level": "debug",
    }))
    assert ha.apply_options(options)
    assert os.environ["BT_NAME"] == "set explicitly"  # explicit env wins
    assert os.environ["BT_ADAPTER"] == "hci1"
    assert os.environ["MA_TOKEN"] == "secret"
    assert "MA_URL" not in os.environ  # empty options are left unset
    assert os.environ["LAN_PORT"] == "8080"
    assert os.environ["LOG_LEVEL"] == "DEBUG"
    assert not ha.apply_options(tmp_path / "missing.json")


def test_ingress_port_only_answers_the_ingress_proxy() -> None:
    async def scenario() -> None:
        # The test client connects from 127.0.0.1, i.e. not the ingress proxy.
        server = TestServer(create_app(None, None, 120))  # type: ignore[arg-type]
        await server.start_server()
        port = server.port
        await server.close()

        restricted = TestServer(create_app(None, None, 120, ingress_port=port), port=port)  # type: ignore[arg-type]
        async with TestClient(restricted) as client:
            assert (await client.get("/")).status == 403

        lan = TestServer(create_app(None, None, 120, ingress_port=port + 1))  # type: ignore[arg-type]
        async with TestClient(lan) as client:
            assert (await client.get("/")).status == 200

    asyncio.run(scenario())


def test_web_ui_uses_relative_urls_for_ingress() -> None:
    # Under HA ingress the page lives below /api/hassio_ingress/<token>/.
    html = files("toothspin").joinpath("index.html").read_text()
    assert not re.findall(r"""(?:href|src)="/|(?:fetch|post|register)\(["`]/|= `/api/""", html)
    manifest = json.loads(files("toothspin").joinpath("static/manifest.webmanifest").read_text())
    assert not any(icon["src"].startswith("/") for icon in manifest["icons"])
    assert not manifest["start_url"].startswith("/")
