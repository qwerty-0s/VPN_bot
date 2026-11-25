import json
from copy import deepcopy
from dataclasses import replace

import pytest
from aiohttp import ClientSession, CookieJar, web
from aiohttp.test_utils import TestServer

from vpn_bot.domain import RetryLater, Subscription
from vpn_bot.integrations.xui import XUI
from vpn_bot.settings import Settings


def _make_fake_panel(
    rows,
    clients_by_email,
    *,
    lose_add_response=False,
    ignore_update=False,
    adds=None,
    attaches=None,
    updates=None,
):
    adds = adds if adds is not None else []
    attaches = attaches if attaches is not None else []
    updates = updates if updates is not None else []
    state = {"lose_add": lose_add_response, "ignore_update": ignore_update}

    async def login(request):
        assert dict(await request.post()) == {"username": "user", "password": "test"}
        response = web.json_response({"success": True})
        response.set_cookie("3x-ui", "test-session")
        return response

    async def handle_list(request):
        assert request.cookies.get("3x-ui") == "test-session"
        return web.json_response({"success": True, "obj": deepcopy(rows)})

    async def handle_get(request):
        assert request.cookies.get("3x-ui") == "test-session"
        email = request.match_info["email"]
        record = clients_by_email.get(email)
        if not record:
            return web.json_response({"success": False, "msg": "Obtain (record not found)", "obj": None})
        return web.json_response({"success": True, "obj": deepcopy(record)})

    async def handle_add(request):
        assert request.cookies.get("3x-ui") == "test-session"
        body = await request.json()
        adds.append(body)
        client = body["client"]
        inbound_ids = body["inboundIds"]
        clients_by_email[client["email"]] = {
            "client": {
                "id": len(clients_by_email) + 1,
                "uuid": client["id"],
                "email": client["email"],
                "flow": client.get("flow", ""),
                "limitIp": client["limitIp"],
                "totalGB": client.get("totalGB", 0),
                "expiryTime": client["expiryTime"],
                "enable": client["enable"],
                "tgId": client["tgId"],
                "subId": client["subId"],
                "reset": client.get("reset", 0),
                "comment": "",
            },
            "inboundIds": list(inbound_ids),
        }
        for row in rows:
            if row["id"] in inbound_ids:
                settings = json.loads(row["settings"])
                settings["clients"].append(deepcopy(client))
                row["settings"] = json.dumps(settings)
        if state["lose_add"]:
            state["lose_add"] = False
            raise web.HTTPServiceUnavailable()
        return web.json_response({"success": True})

    async def handle_attach(request):
        assert request.cookies.get("3x-ui") == "test-session"
        email = request.match_info["email"]
        body = await request.json()
        attaches.append((email, body))
        record = clients_by_email[email]
        c = record["client"]
        inbound_client = {
            "id": c["uuid"],
            "email": c["email"],
            "flow": c.get("flow", ""),
            "limitIp": c["limitIp"],
            "totalGB": c.get("totalGB", 0),
            "expiryTime": c["expiryTime"],
            "enable": c["enable"],
            "tgId": c["tgId"],
            "subId": c["subId"],
            "reset": c.get("reset", 0),
        }
        for iid in body["inboundIds"]:
            if iid not in record["inboundIds"]:
                record["inboundIds"].append(iid)
            for row in rows:
                if row["id"] == iid:
                    settings = json.loads(row["settings"])
                    settings["clients"].append(deepcopy(inbound_client))
                    row["settings"] = json.dumps(settings)
        return web.json_response({"success": True})

    async def handle_update(request):
        assert request.cookies.get("3x-ui") == "test-session"
        email = request.match_info["email"]
        body = await request.json()
        updates.append((email, body))
        # Simulate 3x-ui Go unmarshal check: id must be string UUID, not DB int!
        assert isinstance(body["id"], str)
        if not state["ignore_update"]:
            record = clients_by_email[email]
            record["client"].update({k: v for k, v in body.items() if k != "id"})
            record["client"]["uuid"] = body["id"]
            for row in rows:
                if row["id"] in record["inboundIds"]:
                    settings = json.loads(row["settings"])
                    settings["clients"] = [
                        deepcopy(body) if c.get("email") == email else c for c in settings["clients"]
                    ]
                    row["settings"] = json.dumps(settings)
        return web.json_response({"success": True})

    app = web.Application()
    app.router.add_post("/login", login)
    app.router.add_get("/panel/api/inbounds/list", handle_list)
    app.router.add_get("/panel/api/clients/get/{email}", handle_get)
    app.router.add_post("/panel/api/clients/add", handle_add)
    app.router.add_post("/panel/api/clients/{email}/attach", handle_attach)
    app.router.add_post("/panel/api/clients/update/{email}", handle_update)
    return app, state


def _shared_inbounds():
    return [
        {
            "id": 4,
            "remark": "new-reality",
            "port": 52560,
            "protocol": "vless",
            "enable": True,
            "expiryTime": 0,
            "settings": json.dumps({"clients": [{"id": "other-uuid", "email": "other_user"}]}),
        },
        {
            "id": 5,
            "remark": "new-reality WARP",
            "port": 54346,
            "protocol": "vless",
            "enable": True,
            "expiryTime": 0,
            "settings": json.dumps({"clients": [{"id": "other-uuid", "email": "other_user"}]}),
        },
    ]


async def test_panel_multi_inbound_add_recovery_and_update():
    rows = _shared_inbounds()
    clients_by_email = {}
    adds, updates = [], []
    app, state = _make_fake_panel(rows, clients_by_email, lose_add_response=True, adds=adds, updates=updates)

    async with TestServer(app) as server, ClientSession(cookie_jar=CookieJar(unsafe=True)) as session:
        panel = XUI(
            session,
            str(server.make_url("")),
            "user",
            "test",
            inbounds=("new-reality", "new-reality WARP"),
        )
        sub1 = Subscription(1, "uuid-1", "tg_1", "short1", "sub1", 1800000000000, 3)

        # Lost HTTP response on initial add triggers RetryLater, but client exists in panel.
        with pytest.raises(RetryLater):
            await panel.ensure(sub1)
        assert len(adds) == 1
        assert adds[0]["inboundIds"] == [4, 5]

        # Next attempt recovers using get + update without calling add again.
        result = await panel.ensure(sub1)
        assert result is None
        assert len(adds) == 1
        assert len(updates) == 1

        # Second distinct user shares the same two inbounds without conflict.
        sub2 = Subscription(2, "uuid-2", "tg_2", "short2", "sub2", 1800000000000, 1)
        assert await panel.ensure(sub2) is None
        assert len(adds) == 2

        # Renewal updates both inbounds for user 1.
        renewed = replace(sub1, expiry_ms=1900000000000, devices=5)
        assert await panel.ensure(renewed) is None
        for row in rows:
            clients = {c["email"]: c for c in json.loads(row["settings"])["clients"]}
            assert "other_user" in clients
            assert clients["tg_1"]["expiryTime"] == 1900000000000
            assert clients["tg_1"]["limitIp"] == 5
            assert clients["tg_1"]["subId"] == "sub1"
            assert clients["tg_2"]["limitIp"] == 1

        # Silent panel ignore fails read-after-write check.
        state["ignore_update"] = True
        with pytest.raises(RetryLater, match="did not confirm"):
            await panel.ensure(replace(renewed, expiry_ms=2000000000000))


async def test_panel_attaches_missing_inbound_for_existing_client():
    rows = _shared_inbounds()
    initial_client = {
        "id": "uuid-1",
        "email": "tg_1",
        "flow": "",
        "limitIp": 1,
        "totalGB": 0,
        "expiryTime": 1000,
        "enable": True,
        "tgId": 0,
        "subId": "sub1",
        "reset": 0,
    }
    rows[0]["settings"] = json.dumps({"clients": [initial_client]})
    clients_by_email = {
        "tg_1": {
            "client": {**initial_client, "id": 10, "uuid": "uuid-1", "comment": "vip"},
            "inboundIds": [4],
        }
    }
    attaches, updates = [], []
    app, _ = _make_fake_panel(rows, clients_by_email, attaches=attaches, updates=updates)

    async with TestServer(app) as server, ClientSession(cookie_jar=CookieJar(unsafe=True)) as session:
        panel = XUI(
            session,
            str(server.make_url("")),
            "user",
            "test",
            inbounds=("new-reality", "new-reality WARP"),
        )
        sub = Subscription(999, "uuid-1", "tg_1", "short1", "sub1", 2000, 2)
        assert await panel.ensure(sub) is None
        assert attaches == [("tg_1", {"inboundIds": [5]})]
        assert updates[0][1]["comment"] == "vip"
        assert updates[0][1]["tgId"] == 999
        assert updates[0][1]["limitIp"] == 2
        assert clients_by_email["tg_1"]["inboundIds"] == [4, 5]


async def test_panel_rejects_missing_disabled_or_conflicting_inbounds():
    rows = _shared_inbounds()
    sub = Subscription(1, "uuid-1", "tg_1", "short1", "sub1", 100, 1)

    with pytest.raises(ValueError, match="At least one target inbound"):
        XUI(None, "https://panel.example", "user", "pass", inbounds=())

    panel = XUI(None, "https://panel.example", "user", "pass", inbounds=("new-reality", "Missing"))
    with pytest.raises(RetryLater, match="not found"):
        panel._resolve_inbounds(rows)

    disabled = deepcopy(rows)
    disabled[1]["enable"] = False
    panel_ok = XUI(
        None, "https://panel.example", "user", "pass", inbounds=("new-reality", "new-reality WARP")
    )
    with pytest.raises(RetryLater, match="disabled"):
        panel_ok._resolve_inbounds(disabled)

    conflict_rows = deepcopy(rows)
    conflict_rows[0]["settings"] = json.dumps({"clients": [{"id": "other-uuid", "email": "tg_1"}]})
    with pytest.raises(RetryLater, match="conflict"):
        panel_ok._check_conflicts(conflict_rows, sub)


async def test_panel_csrf_caching_and_reset_on_error():
    get_root_count = 0

    async def get_root(request):
        nonlocal get_root_count
        get_root_count += 1
        return web.Response(
            text='<html><head><meta name="csrf-token" content="test-token-123"></head></html>',
            content_type="text/html",
        )

    async def login(request):
        assert request.headers.get("x-csrf-token") == "test-token-123"
        return web.json_response({"success": True})

    async def handle_list(request):
        assert request.headers.get("x-csrf-token") == "test-token-123"
        return web.json_response({"success": True, "obj": []})

    app = web.Application()
    app.router.add_get("/", get_root)
    app.router.add_post("/login", login)
    app.router.add_get("/panel/api/inbounds/list", handle_list)

    async with TestServer(app) as server, ClientSession() as session:
        panel = XUI(
            session,
            str(server.make_url("")),
            "user",
            "pass",
            inbounds=("new-reality", "new-reality WARP"),
        )
        await panel._request("POST", "/login")
        assert get_root_count == 1
        assert panel.csrf_token == "test-token-123"

        await panel._request("GET", "/panel/api/inbounds/list")
        assert get_root_count == 1

        panel._reset_csrf()
        assert panel.csrf_token is None
        assert panel._csrf_checked is False

        await panel._request("GET", "/panel/api/inbounds/list")
        assert get_root_count == 2


def test_settings_loads_and_validates_panel_inbounds(monkeypatch):
    env = {
        "API_TOKEN": "123456:token",
        "WEBHOOK_URL": "https://vpn.example.com/webhook",
        "TELEGRAM_WEBHOOK_SECRET": "secret_123",
        "PUBLIC_URL": "https://vpn.example.com",
        "YOO_SHOP_ID": "shop",
        "YOO_SECRET_KEY": "secret",
        "YOO_RETURN_URL": "https://t.me/bot",
        "XUI_API": "https://panel.example.com/base",
        "XUI_USER": "admin",
        "XUI_PASS": "pass",
        "XUI_SUB_URL": "https://sub.example.com/sub",
        "XUI_INBOUNDS": " new-reality , new-reality WARP ",
    }
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    settings = Settings.load()
    assert settings.panel_inbounds == ("new-reality", "new-reality WARP")

    monkeypatch.setenv("XUI_INBOUNDS", "new-reality,,new-reality WARP")
    with pytest.raises(ValueError, match="XUI_INBOUNDS"):
        Settings.load()

    monkeypatch.setenv("XUI_INBOUNDS", "new-reality,new-reality")
    with pytest.raises(ValueError, match="duplicates"):
        Settings.load()
