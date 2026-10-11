"""Payment and subscription use cases, independent of SQL and transports."""

import asyncio
import logging
import secrets
import time
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
        async with self.store.transaction(order.telegram_id) as tx:
            order = await tx.order(order_id)
            if order.payment_id:
                return order
            if order.status == "review" or self.clock() - order.created_ms >= 23 * 60 * 60 * 1000:
                await tx.save_order(replace(order, status="review"))
                needs_review = True
            else:
                needs_review = False
                remote = await asyncio.wait_for(self.gateway.create(order), timeout=20)
                self._validate(order, remote)
                if not remote.confirmation_url and remote.status == "pending":
                    raise InvalidPayment("Missing confirmation URL")
                order = replace(
                    order, payment_id=remote.id, confirmation_url=remote.confirmation_url, status="pending"
                )
                await tx.save_order(order)
        if needs_review:
            raise ManualReview("Creation retry window expired; reconcile with YooKassa")
        return order

    async def confirm(self, order_id, telegram_id=None):
        order = await self.store.order(order_id)
        if not order or (telegram_id is not None and order.telegram_id != telegram_id):
            raise NotFound("Order not found")
        if order.status == "review":
            raise ManualReview("Legacy or ambiguous payment needs review")
        if not order.payment_id:
            raise RetryLater("Payment is still being created")
        remote = await self.gateway.fetch(order.payment_id)
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
                order = replace(current, status="succeeded", applied=True)
                await tx.save_order(order)
            else:
                order = replace(current, status=remote.status)
                await tx.save_order(order)
        if order.applied:
            await self.sync(order.telegram_id)
        return order

    async def webhook(self, payment_id):
        order = await self.store.by_payment(payment_id)
        if not order:
            # Can arrive between provider creation and local binding; request redelivery.
            raise RetryLater("Payment not yet bound to a local order")
        return await self.confirm(order.id)

    async def sync(self, telegram_id):
        # Serialize across processes while applying an ABSOLUTE panel state.
        # If the response/commit is lost, retry locates the persisted UUID in the panel.
        async with self.store.transaction(telegram_id) as tx:
            subscription = await tx.subscription(telegram_id)
            if subscription and not subscription.synced:
                port = await asyncio.wait_for(self.panel.ensure(subscription), timeout=20)
                subscription = replace(subscription, port=port, synced=True)
                await tx.save_subscription(subscription)
            return subscription

    async def trial(self, telegram_id):
        async with self.store.transaction(telegram_id) as tx:
            subscription = await tx.subscription(telegram_id)
            if not subscription:
                subscription = self._new_subscription(telegram_id, self.clock() + 3 * DAY_MS, 1)
                await tx.save_subscription(subscription)
        # Existing subscriptions are returned without granting a second trial.
        return await self.sync(telegram_id)

    async def reconcile(self):
        for order in await self.store.pending_orders():
            try:
                if not order.payment_id:
                    order = await self.create_reserved(order.id)
                await self.confirm(order.id)
            except Exception as exc:
                # Never log response bodies, credentials, metadata or payment URLs.
                log.warning("Order reconciliation failed (%s)", type(exc).__name__)
        for subscription in await self.store.unsynced():
            try:
                await self.sync(subscription.telegram_id)
            except Exception as exc:
                log.warning("Panel reconciliation failed (%s)", type(exc).__name__)

    async def notify(self, send):
        for candidate in await self.store.pending_notifications():
            try:
                async with self.store.transaction(candidate.telegram_id) as tx:
                    order = await tx.order(candidate.id)
                    subscription = await tx.subscription(candidate.telegram_id)
                    if not order.notified and subscription and subscription.synced:
                        await asyncio.wait_for(send(subscription), timeout=10)
                        await tx.save_order(replace(order, notified=True))
            except Exception as exc:
                log.warning("Subscription notification failed (%s)", type(exc).__name__)
