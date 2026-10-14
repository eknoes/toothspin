import asyncio

from aiohttp import web
from aiohttp.test_utils import TestServer

from toothspin import ha, setup_check
from toothspin.setup_check import AUTO, Adapter, choose

HA_DONGLE = Adapter("hci0", "00:11:22:33:44:55", "homeassistant")
SPARE = Adapter("hci1", "AA:BB:CC:DD:EE:FF", "ToothSpin")


def test_auto_takes_the_adapter_home_assistant_doesnt_use() -> None:
    usage = {HA_DONGLE.address: ha.USED, SPARE.address: ha.DISABLED}
    result = choose(AUTO, [HA_DONGLE, SPARE], usage)
    assert result.adapter is SPARE
    assert result.problem is None


def test_adapter_shared_with_home_assistant_works_with_a_warning() -> None:
    usage = {HA_DONGLE.address: ha.USED}
    for configured in ("hci0", AUTO):
        result = choose(configured, [HA_DONGLE], usage)
        assert result.adapter is HA_DONGLE
        assert result.problem is not None and not result.problem.fatal
        assert any("second" in step for step in result.problem.steps)


def test_configured_adapter_wins_over_a_free_one() -> None:
    result = choose("hci0", [HA_DONGLE, SPARE], {HA_DONGLE.address: ha.USED})
    assert result.adapter is HA_DONGLE
    assert result.problem is not None and not result.problem.fatal


def test_missing_configured_adapter_lists_the_others() -> None:
    result = choose("hci1", [HA_DONGLE], {HA_DONGLE.address: ha.USED})
    assert result.adapter is None
    assert result.problem is not None and result.problem.fatal
    assert "hci0" in result.problem.text and "used by Home Assistant" in result.problem.text


def test_no_adapter() -> None:
    result = choose(AUTO, [], None)
    assert result.adapter is None and result.problem is not None


def test_discovered_adapter_works_but_warns() -> None:
    usage = {HA_DONGLE.address: ha.USED, SPARE.address: ha.OFFERED}
    result = choose(AUTO, [HA_DONGLE, SPARE], usage)
    assert result.adapter is SPARE
    assert result.problem is not None and not result.problem.fatal


def test_outside_home_assistant_auto_takes_the_first() -> None:
    assert choose(AUTO, [HA_DONGLE, SPARE], None).adapter is HA_DONGLE


def _fake_home_assistant(entries, flows, calls):  # noqa: ANN001, ANN202
    async def websocket(request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        await ws.send_json({"type": "auth_required"})
        auth = await ws.receive_json()
        assert auth == {"type": "auth", "access_token": "token"}
        await ws.send_json({"type": "auth_ok"})
        async for msg in ws:
            command = msg.json()
            result = {"config_entries/get": entries, "config_entries/flow/progress": flows}
            await ws.send_json({"id": command["id"], "type": "event", "event": {}})
            await ws.send_json(
                {"id": command["id"], "type": "result", "success": True,
                 "result": result[command["type"]]}
            )
        return ws

    async def options(request: web.Request) -> web.Response:
        calls.append(await request.json())
        return web.json_response({"result": "ok", "data": {}})

    app = web.Application()
    app.router.add_get("/core/websocket", websocket)
    app.router.add_post("/addons/self/options", options)
    return app


def test_reads_adapter_usage_from_home_assistant(monkeypatch) -> None:
    entries = [
        {"title": "Realtek Bluetooth (00:11:22:33:44:55)", "source": "usb", "disabled_by": None},
        {"title": "CSR (aa:bb:cc:dd:ee:ff)", "source": "usb", "disabled_by": "user"},
        {"title": "Broadcom (11:11:11:11:11:11)", "source": "ignore", "disabled_by": None},
    ]
    flows = [
        {"handler": "bluetooth", "context": {"unique_id": "22:22:22:22:22:22"}},
        {"handler": "zha", "context": {"unique_id": "33:33:33:33:33:33"}},
    ]

    async def scenario() -> dict[str, str]:
        async with TestServer(_fake_home_assistant(entries, flows, [])) as server:
            monkeypatch.setenv("SUPERVISOR_API", str(server.make_url("")).rstrip("/"))
            return await ha.bluetooth_adapter_usage()

    monkeypatch.setenv("SUPERVISOR_TOKEN", "token")
    assert asyncio.run(scenario()) == {
        "00:11:22:33:44:55": ha.USED,
        "AA:BB:CC:DD:EE:FF": ha.DISABLED,
        "11:11:11:11:11:11": ha.IGNORED,
        "22:22:22:22:22:22": ha.OFFERED,
    }


def test_shows_in_sidebar_only_once(tmp_path, monkeypatch) -> None:
    calls: list[dict] = []
    marker = tmp_path / "sidebar"

    async def scenario() -> None:
        async with TestServer(_fake_home_assistant([], [], calls)) as server:
            monkeypatch.setenv("SUPERVISOR_API", str(server.make_url("")).rstrip("/"))
            await ha.show_in_sidebar(marker)
            await ha.show_in_sidebar(marker)

    monkeypatch.setenv("SUPERVISOR_TOKEN", "token")
    asyncio.run(scenario())
    assert calls == [{"ingress_panel": True}]


def test_problem_markdown_numbers_steps() -> None:
    problem = setup_check.Problem("T", "Text.", ["One", "Two"])
    assert problem.as_markdown() == "Text.\n\n1. One\n2. Two"


def test_setup_page_explains_the_blocking_problem_and_missing_token() -> None:
    from aiohttp.test_utils import TestClient

    from toothspin.web import create_setup_app

    status = setup_check.Status(app=True, ma_token=False)
    status.problem = choose(AUTO, [], None).problem

    async def scenario() -> dict:
        async with TestClient(TestServer(create_setup_app(status, None))) as client:
            return (await (await client.get("/api/state")).json())["setup"]

    setup = asyncio.run(scenario())
    assert setup["problem"]["title"] == "No Bluetooth adapter found"
    token = next(c for c in setup["checks"] if c["title"] == "Music Assistant token")
    assert token["ok"] is False
    assert any("Configuration" in step for step in token["steps"])
