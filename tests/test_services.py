import asyncio
from dataclasses import replace
from unittest.mock import AsyncMock

import pytest

from vpn_bot.domain import (
    DAY_MS,
    InvalidPayment,
    ManualReview,
    NotFound,
    Order,
    RetryLater,
    UnreachableUser,
    kopecks,
)
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


async def test_mark_notified_and_confirm_flag(service):
    order = await service.purchase(54, 1, 1, "mn1")
    assert not (await service.store.order(order.id)).notified

    # mark_notified on pending order
    res = await service.mark_notified(order.id)
    assert res.notified is True
    assert (await service.store.order(order.id)).notified is True

    # idempotent call
    res2 = await service.mark_notified(order.id)
    assert res2.notified is True

    # unknown order
    assert await service.mark_notified("non-existent") is None

    # confirm with mark_notified=True
    order2 = await service.purchase(55, 1, 1, "mn2")
    service.gateway.succeed(order2)
    confirmed = await service.confirm(order2.id, mark_notified=True)
    assert confirmed.notified is True
    assert (await service.store.order(order2.id)).notified is True


async def test_create_reserved_does_not_hold_db_transaction_during_gateway_create(service):
    unreserved = Order("unres-1", "req-nb1", 60, 10000, 30, 1, service.clock(), service.return_url)
    async with service.store.transaction(60) as tx:
        await tx.add_order(unreserved)

    in_gateway = asyncio.Event()
    release_gateway = asyncio.Event()
    original_create = service.gateway.create

    async def slow_create(ord_arg):
        in_gateway.set()
        await release_gateway.wait()
        return await original_create(ord_arg)

    service.gateway.create = slow_create
    task = asyncio.create_task(service.create_reserved("unres-1"))
    await in_gateway.wait()

    # DB transaction on another account succeeds immediately
    async with service.store.transaction(999) as tx:
        await tx.subscription(999)

    release_gateway.set()
    res = await task
    assert res.payment_id is not None


async def test_sync_does_not_hold_db_transaction_during_panel_ensure(service):
    order = await service.purchase(61, 1, 1, "nb2")
    service.gateway.succeed(order)
    await service.confirm(order.id)
    sub = await service.store.subscription(61)
    async with service.store.transaction(61) as tx:
        await tx.save_subscription(replace(sub, synced=False))

    in_panel = asyncio.Event()
    release_panel = asyncio.Event()
    original_ensure = service.panel.ensure

    async def slow_ensure(s):
        in_panel.set()
        await release_panel.wait()
        return await original_ensure(s)

    service.panel.ensure = slow_ensure
    task = asyncio.create_task(service.sync(61))
    await in_panel.wait()

    # DB transaction succeeds immediately while panel.ensure is suspended
    async with service.store.transaction(999) as tx:
        await tx.subscription(999)

    release_panel.set()
    res = await task
    assert res.synced is True


async def test_notify_does_not_hold_db_transaction_during_send(service):
    order = await service.purchase(62, 1, 1, "nb3")
    service.gateway.succeed(order)
    await service.confirm(order.id)

    in_send = asyncio.Event()
    release_send = asyncio.Event()

    async def slow_send(s):
        in_send.set()
        await release_send.wait()

    task = asyncio.create_task(service.notify(slow_send))
    await in_send.wait()

    # DB transaction succeeds immediately while send is waiting
    async with service.store.transaction(999) as tx:
        await tx.subscription(999)

    release_send.set()
    await task
    assert (await service.store.order(order.id)).notified is True


async def test_notify_marks_notified_on_unreachable_user(service):
    order = await service.purchase(63, 1, 1, "perm_unreach")
    service.gateway.succeed(order)
    await service.confirm(order.id)

    failing_send = AsyncMock(side_effect=UnreachableUser("User blocked"))
    await service.notify(failing_send)

    updated = await service.store.order(order.id)
    assert updated.notified is True

    next_send = AsyncMock()
    await service.notify(next_send)
    assert next_send.await_count == 0


async def test_reconcile_moves_invalid_payment_to_review(service):
    order = await service.purchase(81, 1, 1, "inv-pay")
    service.gateway.succeed(order)
    # Corrupt remote amount to trigger InvalidPayment
    service.gateway.payments[order.id] = replace(service.gateway.payments[order.id], amount=999999)

    await service.reconcile()

    updated = await service.store.order(order.id)
    assert updated.status == "review"
    assert order.id not in [o.id for o in await service.store.pending_orders()]


async def test_trial_existing_subscription_suppresses_retry_later_when_panel_fails(service):
    first = await service.trial(82)
    assert first.synced is True

    # When panel fails, second call on existing subscription should not raise RetryLater
    service.panel.fail = True
    second = await service.trial(82)
    assert second.uuid == first.uuid
    assert second.telegram_id == 82


async def test_notify_deduplicates_by_telegram_id(service):
    o1 = await service.purchase(83, 1, 1, "dedup-1")
    service.gateway.succeed(o1)
    await service.confirm(o1.id, mark_notified=False)

    o2 = await service.purchase(83, 1, 1, "dedup-2")
    service.gateway.succeed(o2)
    await service.confirm(o2.id, mark_notified=False)

    # Both orders are applied and not notified
    assert (await service.store.order(o1.id)).notified is False
    assert (await service.store.order(o2.id)).notified is False

    send = AsyncMock()
    await service.notify(send)

    # Exactly 1 notification sent to user 83
    assert send.await_count == 1
    assert (await service.store.order(o1.id)).notified is True
    assert (await service.store.order(o2.id)).notified is True


async def test_sync_retries_when_subscription_state_changes_during_ensure(service):
    order = await service.purchase(84, 1, 1, "race-sync-1")
    service.gateway.succeed(order)
    await service.confirm(order.id)
    sub = await service.store.subscription(84)

    # Unsync the subscription
    async with service.store.transaction(84) as tx:
        await tx.save_subscription(replace(sub, synced=False))

    first_call = True
    original_ensure = service.panel.ensure

    async def race_ensure(s):
        nonlocal first_call
        if first_call:
            first_call = False
            # Simulate a concurrent purchase confirming and changing expiry_ms in DB
            async with service.store.transaction(84) as tx:
                curr = await tx.subscription(84)
                await tx.save_subscription(replace(curr, expiry_ms=curr.expiry_ms + 10 * DAY_MS))
        return await original_ensure(s)

    service.panel.ensure = race_ensure
    synced = await service.sync(84)
    assert synced.synced is True
    assert service.panel.state[sub.uuid].expiry_ms == synced.expiry_ms


async def test_confirm_does_not_mark_notified_if_sync_fails(service):
    order = await service.purchase(85, 1, 1, "k-sync-fail")
    service.gateway.succeed(order)
    service.panel.fail = True

    with pytest.raises(RetryLater):
        await service.confirm(order.id, mark_notified=True)

    curr_order = await service.store.order(order.id)
    assert curr_order.applied is True
    assert curr_order.notified is False

    service.panel.fail = False
    await service.reconcile()
    send = AsyncMock()
    await service.notify(send)
    assert send.await_count == 1
    assert (await service.store.order(order.id)).notified is True


async def test_notify_skips_unsynced_subscription(service):
    order = await service.purchase(86, 1, 1, "k-notify-unsynced")
    service.gateway.succeed(order)
    service.panel.fail = True
    with pytest.raises(RetryLater):
        await service.confirm(order.id)

    send = AsyncMock()
    await service.notify(send)
    assert send.await_count == 0
    assert (await service.store.order(order.id)).notified is False

    service.panel.fail = False
    await service.sync(86)
    await service.notify(send)
    assert send.await_count == 1
    assert (await service.store.order(order.id)).notified is True


async def test_multiple_users_sync_with_shared_none_port(service):
    service.panel.ensure = AsyncMock(return_value=None)
    sub1 = await service.trial(101)
    sub2 = await service.trial(102)
    assert sub1.synced is True
    assert sub1.port is None
    assert sub2.synced is True
    assert sub2.port is None
