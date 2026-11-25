"""Payment and subscription use cases, independent of SQL and transports."""

import asyncio
import logging
import secrets
import time
import weakref
from collections import defaultdict
from contextlib import suppress
from dataclasses import replace
from uuid import uuid4

from .domain import (
    DAY_MS,
    InvalidPayment,
    ManualReview,
    NotFound,
    Order,
    RetryLater,
    Subscription,
    UnreachableUser,
)
from .ports import Panel, PaymentGateway, Store

log = logging.getLogger(__name__)


class Service:
    def __init__(
        self,
        store: Store,
        gateway: PaymentGateway,
        panel: Panel,
        *,
        shop_id: str,
        test_payments: bool,
        return_url: str,
        tariffs: dict,
        clock=lambda: int(time.time() * 1000),
    ):
        self.store, self.gateway, self.panel = store, gateway, panel
        self.shop_id, self.test_payments = shop_id, test_payments
        self.return_url, self.tariffs, self.clock = return_url, tariffs, clock
        self._user_locks: weakref.WeakValueDictionary[int, asyncio.Lock] = (
            weakref.WeakValueDictionary()
        )

    def _get_user_lock(self, telegram_id: int) -> asyncio.Lock:
        lock = self._user_locks.get(telegram_id)
        if lock is None:
            lock = asyncio.Lock()
            self._user_locks[telegram_id] = lock
        return lock

    def _new_subscription(self, telegram_id, expiry_ms, devices):
        short_id = secrets.token_urlsafe(24)
        return Subscription(
            telegram_id, str(uuid4()), f"tg_{telegram_id}", short_id, short_id, expiry_ms, devices
        )

    def _validate(self, order, remote):
        if (
            remote.amount != order.amount
            or remote.currency != "RUB"
            or remote.shop_id != self.shop_id
            or remote.test != self.test_payments
            or str(remote.metadata.get("telegram_id")) != str(order.telegram_id)
            or (not order.legacy and remote.metadata.get("order_id") != order.id)
            or (order.payment_id and remote.id != order.payment_id)
        ):
            raise InvalidPayment("Payment does not match the stored order")
        if remote.status not in ("pending", "waiting_for_capture", "succeeded", "canceled"):
            raise InvalidPayment("Unknown payment status")
        if remote.status == "succeeded" and not remote.paid:
            raise InvalidPayment("Succeeded payment is not paid")

    async def purchase(self, telegram_id, months, devices, request_key):
        tariff = self.tariffs.get((months, devices))
        if not tariff:
            raise ValueError("Unknown tariff")
        async with self.store.transaction(telegram_id) as tx:
            order = await tx.by_request(request_key)
            if not order:
                order = Order(
                    str(uuid4()),
                    request_key,
                    telegram_id,
                    tariff["price"] * 100,
                    tariff["days"],
                    devices,
                    self.clock(),
                    self.return_url,
                )
                await tx.add_order(order)
            elif order.telegram_id != telegram_id or order.days != tariff["days"] or order.devices != devices:
                raise InvalidPayment("Request key belongs to another purchase")
        return await self.create_reserved(order.id)

    async def create_reserved(self, order_id):
        order = await self.store.order(order_id)
        if not order:
            raise NotFound("Order not found")
        # Bound orders are never POSTed again. Store reservation survives timeouts.
        if order.payment_id:
            return order
        lock = self._get_user_lock(order.telegram_id)
        async with lock:
            order = await self.store.order(order_id)
            if not order:
                raise NotFound("Order not found")
            if order.payment_id:
                return order
            if order.status == "review" or self.clock() - order.created_ms >= 23 * 60 * 60 * 1000:
                async with self.store.transaction(order.telegram_id) as tx:
                    current = await tx.order(order_id)
                    if current and current.payment_id:
                        return current
                    if current and current.status != "review":
                        await tx.save_order(replace(current, status="review"))
                raise ManualReview("Creation retry window expired; reconcile with YooKassa")

            remote = await asyncio.wait_for(self.gateway.create(order), timeout=20)
            self._validate(order, remote)
            if not remote.confirmation_url and remote.status == "pending":
                raise InvalidPayment("Missing confirmation URL")
            async with self.store.transaction(order.telegram_id) as tx:
                current = await tx.order(order_id)
                if not current:
                    raise NotFound("Order not found")
                if current.payment_id:
                    return current
                order = replace(
                    current,
                    payment_id=remote.id,
                    confirmation_url=remote.confirmation_url,
                    status="pending",
                )
                await tx.save_order(order)
            return order

    async def confirm(self, order_id, telegram_id=None, mark_notified=False):
        order = await self.store.order(order_id)
        if not order or (telegram_id is not None and order.telegram_id != telegram_id):
            raise NotFound("Order not found")
        if order.status == "review":
            raise ManualReview("Legacy or ambiguous payment needs review")
        if not order.payment_id:
            raise RetryLater("Payment is still being created")
        remote = await asyncio.wait_for(self.gateway.fetch(order.payment_id), timeout=20)
        self._validate(order, remote)
        async with self.store.transaction(order.telegram_id) as tx:
            current = await tx.order(order.id)
            if current.applied:
                order = current
            elif current.status == "canceled":
                # Terminal status may not be reversed by a racing stale response.
                if remote.status == "succeeded":
                    raise InvalidPayment("Conflicting terminal payment states")
                order = current
            elif remote.status == "succeeded":
                subscription = await tx.subscription(order.telegram_id)
                expiry = (
                    max(subscription.expiry_ms if subscription else 0, self.clock()) + order.days * DAY_MS
                )
                subscription = (
                    replace(subscription, expiry_ms=expiry, devices=order.devices, synced=False, enabled=True)
                    if subscription
                    else self._new_subscription(order.telegram_id, expiry, order.devices)
                )
                await tx.save_subscription(subscription)
                order = replace(current, status="succeeded", applied=True, notified=False)
                await tx.save_order(order)
            else:
                order = replace(current, status=remote.status)
                await tx.save_order(order)
        if order.applied:
            await self.sync(order.telegram_id)
            if mark_notified:
                order = await self.mark_notified(order.id)
        return order

    async def mark_notified(self, order_id):
        order = await self.store.order(order_id)
        if not order or order.notified:
            return order
        async with self.store.transaction(order.telegram_id) as tx:
            current = await tx.order(order_id)
            if current and not current.notified:
                current = replace(current, notified=True)
                await tx.save_order(current)
            return current

    async def webhook(self, payment_id):
        order = await self.store.by_payment(payment_id)
        if not order:
            # Can arrive between provider creation and local binding; request redelivery.
            raise RetryLater("Payment not yet bound to a local order")
        return await self.confirm(order.id)

    async def sync(self, telegram_id):
        # Serialize across tasks while applying an ABSOLUTE panel state.
        # Panel interaction is executed outside store.transaction.
        lock = self._get_user_lock(telegram_id)
        async with lock:
            while True:
                subscription = await self.store.subscription(telegram_id)
                if not subscription or subscription.synced:
                    return subscription
                port = await asyncio.wait_for(self.panel.ensure(subscription), timeout=20)
                async with self.store.transaction(telegram_id) as tx:
                    current = await tx.subscription(telegram_id)
                    if not current:
                        return None
                    if current.synced:
                        return current
                    if (current.expiry_ms, current.devices, current.uuid) == (
                        subscription.expiry_ms,
                        subscription.devices,
                        subscription.uuid,
                    ):
                        current = replace(current, port=port, synced=True)
                        await tx.save_subscription(current)
                        return current
                    # DB state changed during panel.ensure; persist port and retry loop.
                    current = replace(current, port=port)
                    await tx.save_subscription(current)

    async def trial(self, telegram_id):
        is_existing = False
        async with self.store.transaction(telegram_id) as tx:
            subscription = await tx.subscription(telegram_id)
            if not subscription:
                subscription = self._new_subscription(telegram_id, self.clock() + 3 * DAY_MS, 1)
                await tx.save_subscription(subscription)
            else:
                is_existing = True
        # Existing subscriptions are returned without granting a second trial.
        if is_existing:
            with suppress(RetryLater, asyncio.TimeoutError):
                return await self.sync(telegram_id)
            return await self.store.subscription(telegram_id)
        return await self.sync(telegram_id)

    async def reconcile(self):
        for order in await self.store.pending_orders():
            try:
                if not order.payment_id:
                    order = await self.create_reserved(order.id)
                await self.confirm(order.id)
            except InvalidPayment as exc:
                log.warning(
                    "Order %s reconciliation failed due to invalid payment (%s); marked for review",
                    order.id,
                    type(exc).__name__,
                )
                async with self.store.transaction(order.telegram_id) as tx:
                    current = await tx.order(order.id)
                    if current and current.status != "review":
                        await tx.save_order(replace(current, status="review"))
            except Exception as exc:
                # Never log response bodies, credentials, metadata or payment URLs.
                log.warning("Order reconciliation failed (%s)", type(exc).__name__)
        for subscription in await self.store.unsynced():
            try:
                await self.sync(subscription.telegram_id)
            except Exception as exc:
                log.warning("Panel reconciliation failed (%s)", type(exc).__name__)

    async def notify(self, send):
        candidates = await self.store.pending_notifications()
        by_user = defaultdict(list)
        for candidate in candidates:
            by_user[candidate.telegram_id].append(candidate)

        for telegram_id, user_orders in by_user.items():
            try:
                pending_for_user = []
                for o in user_orders:
                    current_order = await self.store.order(o.id)
                    if current_order and not current_order.notified:
                        pending_for_user.append(current_order)
                if not pending_for_user:
                    continue

                subscription = await self.store.subscription(telegram_id)
                if subscription and subscription.synced:
                    try:
                        await asyncio.wait_for(send(subscription), timeout=10)
                    except UnreachableUser as exc:
                        log.warning(
                            "User %s unreachable (%s), marking orders as notified",
                            telegram_id,
                            type(exc).__name__,
                        )
                    for order in pending_for_user:
                        await self.mark_notified(order.id)
            except Exception as exc:
                log.warning("Subscription notification failed (%s)", type(exc).__name__)
