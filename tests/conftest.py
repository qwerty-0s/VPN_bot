import os
from dataclasses import replace
from uuid import uuid4

import pytest

from vpn_bot.domain import RemotePayment, RetryLater
from vpn_bot.services import Service
from vpn_bot.settings import TARIFFS
from vpn_bot.storage import SQLStore, metadata


class Gateway:
    def __init__(self):
        self.payments = {}
        self.creations = 0
        self.fetches = 0
        self.lose_response = False

    async def create(self, order):
        if order.id not in self.payments:
            self.creations += 1
            self.payments[order.id] = RemotePayment(
                str(uuid4()),
                "pending",
                order.amount,
                "RUB",
                False,
                True,
                "shop",
                {"order_id": order.id, "telegram_id": str(order.telegram_id)},
                "https://pay.example/confirm",
            )
        if self.lose_response:
            self.lose_response = False
            raise RetryLater("Response lost after creation")
        return self.payments[order.id]

    async def fetch(self, payment_id):
        self.fetches += 1
        return next(p for p in self.payments.values() if p.id == payment_id)

    def succeed(self, order):
        self.payments[order.id] = replace(self.payments[order.id], status="succeeded", paid=True)


class Panel:
    def __init__(self):
        self.state = {}
        self.fail = False
        self.calls = 0

    async def ensure(self, subscription):
        self.calls += 1
        self.state[subscription.uuid] = subscription
        if self.fail:
            self.fail = False
            raise RetryLater("Response lost after panel update")
        return 10000 + subscription.telegram_id % 50000


@pytest.fixture
async def store(tmp_path):
    # PG_TEST_URL MUST point to a disposable empty test database.
    url = os.getenv("PG_TEST_URL") or f"sqlite+aiosqlite:///{tmp_path}/test.db"
    result = SQLStore(url)
    async with result.engine.begin() as conn:
        await conn.run_sync(metadata.drop_all)
    await result.initialize()
    yield result
    async with result.engine.begin() as conn:
        await conn.run_sync(metadata.drop_all)
    await result.close()


@pytest.fixture
def service(store):
    return Service(
        store,
        Gateway(),
        Panel(),
        shop_id="shop",
        test_payments=True,
        return_url="https://t.me/example_bot",
        tariffs=TARIFFS,
        clock=lambda: 1_800_000_000_000,
    )
