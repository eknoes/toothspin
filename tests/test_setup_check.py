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
            calls.append(command)
            result = {"config_entries/get": entries, "config_entries/flow/progress": flows,
                      "config_entries/ignore_flow": None}
            await ws.send_json({"id": command["id"], "type": "event", "event": {}})
            await ws.send_json(
                {"id": command["id"], "type": "result", "success": True,
                 "result": result[command["type"]]}
            )
        return ws

    async def options(request: web.Request) -> web.Response:
        calls.append(await request.json())
        return web.json_response({"result": "ok", "data": {}})

    async def info(_: web.Request) -> web.Response:
        return web.json_response({"result": "ok", "data": {
            "ingress_port": 1234, "slug": "abc_toothspin",
            "options": {"bluetooth_name": "Kitchen", "take_bluetooth_audio": False}}})

    app = web.Application()
    app.router.add_get("/addons/self/info", info)
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


def test_ignores_the_discovered_adapter_on_request(monkeypatch) -> None:
    calls: list[dict] = []
    flows = [{"flow_id": "f1", "handler": "bluetooth", "context": {"unique_id": "aa:bb:cc:dd:ee:ff"}}]

    async def scenario() -> tuple[bool, bool]:
        async with TestServer(_fake_home_assistant([], flows, calls)) as server:
            monkeypatch.setenv("SUPERVISOR_API", str(server.make_url("")).rstrip("/"))
            return (await ha.ignore_discovered("AA:BB:CC:DD:EE:FF"),
                    await ha.ignore_discovered("11:22:33:44:55:66"))

    monkeypatch.setenv("SUPERVISOR_TOKEN", "token")
    assert asyncio.run(scenario()) == (True, False)
    ignore = [c for c in calls if c["type"] == "config_entries/ignore_flow"]
    # The title keeps the address, so the ignored entry is recognised later.
    assert [(c["flow_id"], c["title"]) for c in ignore] == [("f1", "ToothSpin (AA:BB:CC:DD:EE:FF)")]


def test_links_into_home_assistant_need_the_app() -> None:
    problem = choose(AUTO, [SPARE], {SPARE.address: ha.OFFERED}).problem
    assert problem is not None and problem.action == "ignore-adapter"
    linked = problem.as_markdown("abc_toothspin")
    assert "[Settings → Devices & services](/config/integrations/dashboard)" in linked
    assert "ha:" not in problem.as_markdown()
    shared = setup_check._shared(SPARE).as_markdown("abc_toothspin")  # noqa: SLF001
    assert "(/config/app/abc_toothspin/config)" in shared


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
    token = next(t for t in setup["todo"] if "token" in t["title"])
    assert token["kind"] == "todo"
    assert any("(ha:app-config)" in step for step in token["steps"])


def test_too_old_music_assistant_is_on_the_list() -> None:
    from toothspin.web import _setup_state

    status = setup_check.Status(app=True, ma_token=False, ma_version="2.10.1")
    todo = _setup_state(status, None, None)["todo"]
    assert todo[0]["title"] == "Update Music Assistant" and "2.10.1" in todo[0]["text"]
    status.ma_version = "2.11.0b5"
    assert all(t["title"] != "Update Music Assistant" for t in _setup_state(status, None, None)["todo"])


def test_setting_an_option_keeps_the_others(monkeypatch) -> None:
    calls: list[dict] = []

    async def scenario() -> None:
        async with TestServer(_fake_home_assistant([], [], calls)) as server:
            monkeypatch.setenv("SUPERVISOR_API", str(server.make_url("")).rstrip("/"))
            await ha.set_option("take_bluetooth_audio", True)

    monkeypatch.setenv("SUPERVISOR_TOKEN", "token")
    asyncio.run(scenario())
    assert calls == [{"options": {"bluetooth_name": "Kitchen", "take_bluetooth_audio": True}}]


def test_audio_conflict_comes_first_with_its_action() -> None:
    from toothspin.web import _setup_state

    status = setup_check.Status(app=True, ma_token=False)
    status.audio_conflict = setup_check.ha_audio_takes_bluetooth()
    todo = _setup_state(status, None, None)["todo"]
    assert todo[0]["action"] == "take-bluetooth-audio"
    assert "token" in todo[1]["title"]


def test_standalone_setup_talks_about_its_own_server() -> None:
    from types import SimpleNamespace

    from toothspin.web import _setup_state

    status = setup_check.Status(app=False, ma_token=True)
    starting = SimpleNamespace(connected=False, players=[])
    todo = _setup_state(status, starting, None, "standalone")["todo"]
    assert [t["title"] for t in todo] == ["Starting ToothSpin's Sendspin server…"]
    running = SimpleNamespace(connected=True, players=[])
    todo = _setup_state(status, running, None, "standalone")["todo"]
    assert [t["kind"] for t in todo] == ["hint"]
    assert not any("Music Assistant" in t["title"] for t in todo)
    playing = SimpleNamespace(connected=True, players=[{"player_id": "kitchen"}])
    assert _setup_state(status, playing, None, "standalone")["todo"] == []


def test_home_screen_tip_once_a_phone_is_paired() -> None:
    from types import SimpleNamespace

    from toothspin.web import _setup_state

    status = setup_check.Status(app=True, ma_token=True)
    playing = SimpleNamespace(connected=True, players=[{"player_id": "kitchen"}])
    unpaired = SimpleNamespace(alias="ToothSpin", devices=lambda: [])
    todo = _setup_state(status, playing, unpaired, "standalone")["todo"]
    assert [t["title"] for t in todo] == ["Pair your first phone"]
    paired = SimpleNamespace(alias="ToothSpin", devices=lambda: ["phone"])
    [tip] = _setup_state(status, playing, paired, "standalone")["todo"]
    assert tip["dismissible"] and tip["id"] == "home-screen"
    assert "(faq:home-screen)" in tip["text"]


def test_another_sendspin_version_asks_for_an_update() -> None:
    from toothspin.web import _setup_state

    def titles(version: str | None, mode: str = "music-assistant") -> list[str]:
        status = setup_check.Status(app=True, ma_token=False, ma_version=version)
        return [t["title"] for t in _setup_state(status, None, None, mode, incompatible=True)["todo"]]

    assert titles(None)[0] == "Update Music Assistant or ToothSpin"
    assert titles("2.12.0")[0] == "Update ToothSpin"
    # Too old says so already.
    assert [t for t in titles("2.10.6") if t.startswith("Update")] == ["Update Music Assistant"]
    assert not [t for t in titles(None, "standalone") if t.startswith("Update")]
