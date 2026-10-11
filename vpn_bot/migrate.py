"""Explicit, transactional import of the previous SQLite schema; originals stay intact."""

import asyncio
import json
from dataclasses import asdict
from datetime import datetime, timezone
from uuid import NAMESPACE_URL, uuid5

from dotenv import load_dotenv
from sqlalchemy import MetaData, Table, insert, inspect, select

from .domain import Order, Subscription
from .settings import database_url
from .storage import SQLStore, accounts, metadata, orders, schema, subscriptions


async def migrate(store):
    async with store.engine.begin() as conn:
        names = await conn.run_sync(lambda c: inspect(c).get_table_names())
        if "vpn_schema" in names:
            versions = (await conn.execute(select(schema.c.version))).scalars().all()
            if versions == [1]:
                return {"already_migrated": True}
            raise RuntimeError("Unknown or incomplete schema; inspect before migrating")
        if any(name.startswith("vpn_") for name in names):
            raise RuntimeError("Partial target schema; inspect before migrating")
        await conn.run_sync(metadata.create_all)

        async def rows(name):
            if name not in names:
                return []
            table = await conn.run_sync(lambda c: Table(name, MetaData(), autoload_with=c))
            return (await conn.execute(select(table))).mappings().all()

        seen, imported, payment_count = set(), set(), 0

        async def account(telegram_id):
            if telegram_id not in seen:
                await conn.execute(insert(accounts).values(telegram_id=telegram_id, revision=0))
                seen.add(telegram_id)

        # Current users win over a historical trial_users row with the same id.
        for row in [*await rows("users"), *await rows("trial_users")]:
            user_id = int(row["telegram_id"])
            if user_id in imported:
                continue
            if not row.get("short_id"):
                raise ValueError("Legacy subscription without short_id; reconcile before import")
            await account(user_id)
            subscription = Subscription(
                user_id,
                row["uuid"],
                row["email"],
                row["short_id"],
                row.get("sub_id") or "trial_" + row["email"][-6:],
                int(row["expiry_time"]),
                int(row.get("ip_limit", 1)),
                int(row["port"]),
                True,
                bool(row.get("is_active", True)),
            )
            await conn.execute(insert(subscriptions).values(**asdict(subscription)))
            imported.add(user_id)
        for row in await rows("payments"):
            user_id = int(row["telegram_id"])
            await account(user_id)
            tariff = json.loads(row["tariff_data"])
            days, devices, amount = int(tariff["days"]), int(tariff["devices"]), int(row["amount"])
            if min(days, devices, amount) <= 0:
                raise ValueError("Invalid legacy tariff")
            # These statuses cannot prove whether VPN days were already delivered.
            status = row["status"] if row["status"] in ("pending", "canceled") else "review"
            created = datetime.fromisoformat(row["created_at"])
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            order = Order(
                str(uuid5(NAMESPACE_URL, "yookassa:" + row["payment_id"])),
                "legacy:" + row["payment_id"],
                user_id,
                amount,
                days,
                devices,
                int(created.timestamp() * 1000),
                "",
                row["payment_id"],
                status=status,
                legacy=True,
            )
            await conn.execute(insert(orders).values(**asdict(order)))
            payment_count += 1
        await conn.execute(insert(schema).values(version=1))
        return {"subscriptions": len(imported), "payments": payment_count}


async def main():
    load_dotenv()
    store = SQLStore(database_url())
    try:
        print(await migrate(store))
    finally:
        await store.close()


if __name__ == "__main__":
    asyncio.run(main())
