from dataclasses import replace
from unittest.mock import AsyncMock

from aiohttp import ClientSession, web
from aiohttp.test_utils import TestClient, TestServer

from vpn_bot.domain import DAY_MS, Order, RetryLater
from vpn_bot.integrations.yookassa import YooKassa
from vpn_bot.transport.http import register_routes


async def test_yookassa_wire_contract_exact_money_key_and_async_http():
    requests = []

    async def create(request):
        body = await request.json()
        requests.append((dict(request.headers), body))
        return web.json_response(
            {
                "id": "payment-id",
                "status": "pending",
                "paid": False,
                "test": True,
                "recipient": {"account_id": "shop"},
                "amount": body["amount"],
                "metadata": body["metadata"],
                "confirmation": {"confirmation_url": "https://pay.example/abc"},
            }
        )

    app = web.Application()
    app.router.add_post("/payments", create)
    async with TestServer(app) as server, ClientSession() as session:
        gateway = YooKassa(session, "shop", "test-secret", str(server.make_url("")))
        order = Order("order-id", "request", 1, 10029, 30, 3, 100, "https://return.example")
        assert (await gateway.create(order)).amount == 10029
        await gateway.create(order)
    assert requests[0] == requests[1]
    headers, body = requests[0]
    assert headers["Idempotence-Key"] == order.id
    assert headers["Authorization"].startswith("Basic ")
    assert body["amount"] == {"value": "100.29", "currency": "RUB"}
    assert body["capture"] is True
    assert body["payment_method_data"] == {"type": "bank_card"}


async def test_webhook_refetches_provider_and_preserves_retry_on_failure(service):
    order = await service.purchase(20, 1, 1, "a")
    app = register_routes(web.Application(client_max_size=64 * 1024), service, None, "https://sub.example")
    event = {
        "type": "notification",
        "event": "payment.succeeded",
        "object": {
            "id": order.payment_id,
            "status": "succeeded",
            "amount": {"value": "999999"},
            "metadata": {"telegram_id": "other"},
        },
    }
    async with TestClient(TestServer(app)) as client:
        # Forged event cannot upgrade the still-pending provider payment.
        assert (await client.post("/payments/yookassa", json=event)).status == 200
        assert await service.store.subscription(20) is None
        service.gateway.succeed(order)
        service.panel.fail = True
        assert (await client.post("/payments/yookassa", json=event)).status == 503
        assert (await client.post("/payments/yookassa", json=event)).status == 200
        assert (await client.post("/payments/yookassa", json=event)).status == 200
        assert (await service.store.subscription(20)).expiry_ms == service.clock() + 30 * DAY_MS
        assert (await client.post("/payments/yookassa", json=[])).status == 400
        assert (await client.post("/payments/yookassa", data="x" * 70000)).status == 413
        event["object"]["id"] = "unknown"
        assert (await client.post("/payments/yookassa", json=event)).status == 503


async def test_webhook_amount_mismatch_and_provider_unavailable(service):
    order = await service.purchase(21, 1, 1, "a")
    service.gateway.succeed(order)
    service.gateway.payments[order.id] = replace(service.gateway.payments[order.id], amount=1)
    app = register_routes(web.Application(), service, None, "https://sub.example")
    event = {"type": "notification", "event": "payment.succeeded", "object": {"id": order.payment_id}}
    async with TestClient(TestServer(app)) as client:
        assert (await client.post("/payments/yookassa", json=event)).status == 400
        service.gateway.fetch = AsyncMock(side_effect=RetryLater("offline"))
        assert (await client.post("/payments/yookassa", json=event)).status == 503
    assert await service.store.subscription(21) is None


async def test_short_link_proxy_blocks_expired_and_preserves_panel_sub_id(service):
    upstream = web.Application()
    calls = []

    async def subscription(request):
        calls.append(request.match_info["sub_id"])
        return web.Response(text="encoded-subscription", headers={"Subscription-Userinfo": "expire=999"})

    upstream.router.add_get("/sub/{sub_id}", subscription)
    subscription = await service.trial(22)
    async with TestServer(upstream) as server, ClientSession() as session:
        app = register_routes(web.Application(), service, session, str(server.make_url("/sub")))
        async with TestClient(TestServer(app)) as client:
            assert (await client.get("/sub/missing")).status == 404
            response = await client.get("/sub/" + subscription.short_id)
            assert response.status == 200
            assert await response.text() == "encoded-subscription"
            assert calls == [subscription.sub_id]
            service.clock = lambda: subscription.expiry_ms
            assert (await client.get("/sub/" + subscription.short_id)).status == 403
            assert len(calls) == 1


async def test_startup_routes_telegram_secret_and_shutdown(tmp_path, monkeypatch):
    from aiogram import Bot

    from vpn_bot.app import create_app
    from vpn_bot.settings import Settings

    set_webhook = AsyncMock()
    monkeypatch.setattr(Bot, "set_webhook", set_webhook)
    telegram_request = AsyncMock()
    monkeypatch.setattr(Bot, "__call__", telegram_request)
    settings = Settings(
        "123456:fake",
        "https://bot.example/webhook",
        "secret",
        "https://bot.example",
        f"sqlite+aiosqlite:///{tmp_path}/app.db",
        "shop",
        "test",
        "https://return.example",
        True,
        "https://panel.example",
        "user",
        "password",
        "https://sub.example",
        True,
        "127.0.0.1",
        8443,
    )
    async with TestClient(TestServer(create_app(settings))) as client:
        assert (await client.get("/sub/missing")).status == 404
        update = {
            "update_id": 1,
            "message": {
                "message_id": 1,
                "date": 1800000000,
                "chat": {"id": 1, "type": "private"},
                "from": {"id": 1, "is_bot": False, "first_name": "Test"},
                "text": "/start",
                "entities": [{"type": "bot_command", "offset": 0, "length": 6}],
            },
        }
        assert (await client.post("/webhook", json=update)).status == 401
        assert (
            await client.post("/webhook", json=update, headers={"X-Telegram-Bot-Api-Secret-Token": "secret"})
        ).status == 200
        set_webhook.assert_awaited_once_with(settings.webhook_url, secret_token="secret")
        assert telegram_request.await_count == 1
