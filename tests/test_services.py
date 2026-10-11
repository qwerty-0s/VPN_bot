import asyncio
from dataclasses import replace
from unittest.mock import AsyncMock

import pytest

from vpn_bot.domain import DAY_MS, InvalidPayment, ManualReview, NotFound, RetryLater, kopecks
from vpn_bot.services import Service
from vpn_bot.storage import SQLStore


async def test_creation_recovery_uses_persisted_key_and_payload(service):
    service.gateway.lose_response = True
    with pytest.raises(RetryLater):
        await service.purchase(1, 1, 1, "request")
    reserved = (await service.store.pending_orders())[0]
    service.return_url = "https://changed.example"
    retried = await service.purchase(1, 1, 1, "request")
    assert retried.id == reserved.id
    assert retried.return_url == "https://t.me/example_bot"
    assert service.gateway.creations == 1
    assert await service.store.subscription(1) is None


async def test_double_purchase_callback_creates_one_remote_payment(service):
    a, b = await asyncio.gather(
        service.purchase(30, 1, 1, "same-screen"), service.purchase(30, 1, 1, "same-screen")
    )
    assert a.id == b.id
    assert a.payment_id == b.payment_id
    assert service.gateway.creations == 1


async def test_database_failure_rolls_back_both_grant_and_applied_flag(service, monkeypatch):
    from vpn_bot.storage import SQLTransaction

    order = await service.purchase(31, 1, 1, "a")
    service.gateway.succeed(order)
    original = SQLTransaction.save_order

    async def fail_after_subscription(self, changed):
        if changed.applied:
            raise RuntimeError("Simulated database write failure")
        await original(self, changed)

    monkeypatch.setattr(SQLTransaction, "save_order", fail_after_subscription)
    with pytest.raises(RuntimeError):
        await service.confirm(order.id)
    assert await service.store.subscription(31) is None
    assert not (await service.store.order(order.id)).applied
    assert service.panel.calls == 0
    monkeypatch.setattr(SQLTransaction, "save_order", original)
    await service.confirm(order.id)
    assert (await service.store.subscription(31)).expiry_ms == service.clock() + 30 * DAY_MS


async def test_first_purchase_without_trial_and_duplicate_webhooks(service):
    order = await service.purchase(2, 1, 3, "first")
    service.gateway.succeed(order)
    await asyncio.gather(*(service.webhook(order.payment_id) for _ in range(8)))
    subscription = await service.store.subscription(2)
    assert subscription.expiry_ms == service.clock() + 30 * DAY_MS
    assert subscription.devices == 3
    assert subscription.synced
    assert len(service.panel.state) == 1
    assert service.panel.calls == 1


async def test_distinct_concurrent_purchases_across_connections(service):
    await service.trial(3)
    second_store = SQLStore(service.store.engine.url.render_as_string(hide_password=False))
    second = Service(
        second_store,
        service.gateway,
        service.panel,
        shop_id="shop",
        test_payments=True,
        return_url=service.return_url,
        tariffs=service.tariffs,
        clock=service.clock,
    )
    try:
        a, b = await asyncio.gather(service.purchase(3, 1, 1, "a"), second.purchase(3, 3, 3, "b"))
        service.gateway.succeed(a)
        service.gateway.succeed(b)
        await asyncio.gather(service.confirm(a.id, 3), second.confirm(b.id, 3))
        subscription = await service.store.subscription(3)
        assert subscription.expiry_ms == service.clock() + 123 * DAY_MS
        assert service.panel.state[subscription.uuid].expiry_ms == subscription.expiry_ms
    finally:
        await second_store.close()


async def test_panel_failure_after_side_effect_is_retryable_without_extra_days(service):
    order = await service.purchase(4, 1, 1, "a")
    service.gateway.succeed(order)
    service.panel.fail = True
    with pytest.raises(RetryLater):
        await service.confirm(order.id, 4)
    subscription = await service.store.subscription(4)
    assert not subscription.synced
    assert (await service.store.order(order.id)).applied
    await service.reconcile()
    recovered = await service.store.subscription(4)
    assert recovered.synced
    assert recovered.expiry_ms == subscription.expiry_ms
    assert recovered.uuid == subscription.uuid
    assert len(service.panel.state) == 1


@pytest.mark.parametrize(
    "changed",
    [
        {"amount": 1},
        {"currency": "USD"},
        {"shop_id": "other"},
        {"test": False},
        {"metadata": {"telegram_id": "999", "order_id": "bad"}},
        {"paid": False},
        {"id": "different"},
    ],
)
async def test_payment_mismatch_does_not_grant_access(service, changed):
    order = await service.purchase(5, 1, 1, "a")
    service.gateway.succeed(order)
    remote = replace(service.gateway.payments[order.id], **changed)
    service.gateway.fetch = AsyncMock(return_value=remote)
    with pytest.raises(InvalidPayment):
        await service.confirm(order.id, 5)
    assert await service.store.subscription(5) is None
    assert not (await service.store.order(order.id)).applied


async def test_foreign_owner_rejected_before_provider_call(service):
    order = await service.purchase(6, 1, 1, "a")
    with pytest.raises(NotFound):
        await service.confirm(order.id, 7)
    assert service.gateway.fetches == 0


async def test_expired_creation_never_posts_again(service):
    service.gateway.lose_response = True
    with pytest.raises(RetryLater):
        await service.purchase(7, 1, 1, "a")
    service.clock = lambda: 1_800_000_000_000 + DAY_MS
    with pytest.raises(ManualReview):
        await service.purchase(7, 1, 1, "a")
    assert service.gateway.creations == 1
    assert await service.store.pending_orders() == []


async def test_trial_cannot_be_repeated_or_extend_paid_subscription(service):
    a, b = await asyncio.gather(service.trial(8), service.trial(8))
    assert a.uuid == b.uuid
    assert a.expiry_ms == b.expiry_ms == service.clock() + 3 * DAY_MS
    service.clock = lambda: 1_800_000_000_000 + 10 * DAY_MS
    assert (await service.trial(8)).expiry_ms == a.expiry_ms
    order = await service.purchase(8, 1, 5, "paid")
    service.gateway.succeed(order)
    await service.confirm(order.id)
    subscription = await service.trial(8)
    assert subscription.expiry_ms == service.clock() + 30 * DAY_MS
    assert subscription.devices == 5


async def test_pending_canceled_and_stale_terminal_responses(service):
    order = await service.purchase(9, 1, 1, "a")
    await service.confirm(order.id)
    assert await service.store.subscription(9) is None
    service.gateway.payments[order.id] = replace(service.gateway.payments[order.id], status="canceled")
    await service.confirm(order.id)
    service.gateway.payments[order.id] = replace(service.gateway.payments[order.id], status="pending")
    assert (await service.confirm(order.id)).status == "canceled"
    assert await service.store.subscription(9) is None


async def test_success_never_downgraded_and_notifications_retry(service):
    order = await service.purchase(10, 1, 1, "a")
    service.gateway.succeed(order)
    await service.confirm(order.id)
    service.gateway.payments[order.id] = replace(
        service.gateway.payments[order.id], status="pending", paid=False
    )
    assert (await service.confirm(order.id)).status == "succeeded"
    failed = AsyncMock(side_effect=RuntimeError("Telegram unavailable"))
    await service.notify(failed)
    send = AsyncMock()
    await service.notify(send)
    await service.notify(send)
    assert send.await_count == 1


@pytest.mark.parametrize("value,expected", [("99.00", 9900), ("1.01", 101), ("0.29", 29)])
def test_exact_money(value, expected):
    assert kopecks(value) == expected


@pytest.mark.parametrize("value", ["NaN", "Infinity", "0.001", "0", "-1", "x"])
def test_invalid_money(value):
    with pytest.raises(InvalidPayment):
        kopecks(value)
