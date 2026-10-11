import json
from copy import deepcopy
from dataclasses import replace

import pytest
from aiohttp import ClientSession, CookieJar, web
from aiohttp.test_utils import TestServer

from vpn_bot.domain import RetryLater, Subscription
from vpn_bot.integrations.xui import XUI


async def test_panel_absolute_expiry_and_recovery_after_lost_create_response():
    rows = []
    adds = []
    lose_response = True
    ignore_client = False

    async def login(request):
        assert dict(await request.post()) == {"username": "user", "password": "test"}
        response = web.json_response({"success": True})
        response.set_cookie("3x-ui", "test-session")
        return response

    async def handle(request):
        nonlocal lose_response
        assert request.cookies.get("3x-ui") == "test-session"
        action = request.match_info["action"]
        if action == "list":
            return web.json_response({"success": True, "obj": deepcopy(rows)})
        if action == "keys":
            return web.json_response(
                {"success": True, "obj": {"privateKey": "private", "publicKey": "public"}}
            )
        body = await request.json()
        if action == "add":
            adds.append(body)
            rows.append({**body, "id": 1})
            if lose_response:
                lose_response = False
                raise web.HTTPServiceUnavailable()
        elif action == "update":
            rows[0].update(body)
        elif action == "client" and not ignore_client:
            rows[0]["settings"] = body["settings"]
        return web.json_response({"success": True})

    app = web.Application()
    app.router.add_post("/login", login)
    for method, path, action in [
        ("GET", "/panel/api/inbounds/list", "list"),
        ("GET", "/panel/api/server/getNewX25519Cert", "keys"),
        ("POST", "/panel/api/inbounds/add", "add"),
        ("POST", "/panel/api/inbounds/update/1", "update"),
        ("POST", "/panel/api/inbounds/updateClient/uuid", "client"),
    ]:

        async def endpoint(request, selected=action):
            request.match_info["action"] = selected
            return await handle(request)

        app.router.add_route(method, path, endpoint)
    async with TestServer(app) as server, ClientSession(cookie_jar=CookieJar(unsafe=True)) as session:
        panel = XUI(session, str(server.make_url("")), "user", "test")
        subscription = Subscription(1, "uuid", "tg_1", "short", "sub", 1800000000000, 3)
        with pytest.raises(RetryLater):
            await panel.ensure(subscription)
        port = await panel.ensure(subscription)
        assert len(adds) == 1
        assert port == adds[0]["port"]
        renewed = replace(subscription, expiry_ms=1900000000000, devices=5)
        await panel.ensure(renewed)
        await panel.ensure(renewed)
        client = json.loads(rows[0]["settings"])["clients"][0]
        assert client["expiryTime"] == renewed.expiry_ms
        assert client["limitIp"] == 5
        assert rows[0]["expiryTime"] == 0
        ignore_client = True
        with pytest.raises(RetryLater, match="did not confirm"):
            await panel.ensure(replace(renewed, expiry_ms=2000000000000))


def test_panel_refuses_shared_or_conflicting_identity():
    subscription = Subscription(1, "uuid", "tg_1", "short", "sub", 100, 1)
    rows = [{"protocol": "vless", "settings": {"clients": [{"id": "uuid"}, {"id": "another"}]}}]
    with pytest.raises(RetryLater, match="dedicated"):
        XUI._find(rows, subscription)
    rows = [{"protocol": "vless", "settings": {"clients": [{"id": "other", "email": "tg_1"}]}}]
    with pytest.raises(RetryLater, match="conflict"):
        XUI._find(rows, subscription)
