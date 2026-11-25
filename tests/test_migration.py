import json
import sqlite3

import pytest
from sqlalchemy import inspect

from vpn_bot.migrate import migrate
from vpn_bot.storage import SQLStore


def legacy_database(path, bad_payment=False):
    with sqlite3.connect(path) as conn:
        conn.executescript("""
            CREATE TABLE users (telegram_id INTEGER PRIMARY KEY, uuid TEXT, email TEXT,
                port INTEGER, expiry_time INTEGER, ip_limit INTEGER, short_id TEXT, is_active BOOLEAN);
            CREATE TABLE payments (payment_id TEXT PRIMARY KEY, telegram_id INTEGER, amount INTEGER,
                status TEXT, tariff_data TEXT, created_at TEXT);
        """)
        conn.execute(
            "INSERT INTO users VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (1, "uuid", "12345678", 12000, 1800000000000, 3, "old-short", 1),
        )
        for status in ("pending", "succeeded", "completed", "canceled"):
            conn.execute(
                "INSERT INTO payments VALUES (?, ?, ?, ?, ?, ?)",
                (
                    status,
                    2,
                    9900,
                    status,
                    "bad-json" if bad_payment else json.dumps({"days": 30, "devices": 1}),
                    "2026-01-01T00:00:00",
                ),
            )


async def test_legacy_import_preserves_originals_and_quarantines_success(tmp_path):
    path = tmp_path / "legacy.db"
    legacy_database(path)
    store = SQLStore(f"sqlite+aiosqlite:///{path}")
    try:
        with pytest.raises(RuntimeError, match="Legacy database"):
            await store.initialize()
        result = await migrate(store)
        assert result == {"subscriptions": 1, "payments": 4}
        assert await migrate(store) == {"already_migrated": True}
        await store.initialize()
        subscription = await store.subscription(1)
        assert subscription.short_id == "old-short"
        assert subscription.sub_id == "trial_345678"
        assert subscription.expiry_ms == 1800000000000
        assert (await store.by_payment("succeeded")).status == "review"
        assert (await store.by_payment("completed")).status == "review"
        assert (await store.by_payment("pending")).status == "pending"
        assert await store.subscription(2) is None  # First-purchase payment may precede VPN user.
        with sqlite3.connect(path) as conn:
            assert conn.execute("SELECT COUNT(*) FROM payments").fetchone()[0] == 4
            assert (
                conn.execute("SELECT status FROM payments WHERE payment_id='succeeded'").fetchone()[0]
                == "succeeded"
            )
    finally:
        await store.close()


async def test_migration_rolls_back_ddl_and_data_on_corruption(tmp_path):
    path = tmp_path / "bad.db"
    legacy_database(path, bad_payment=True)
    store = SQLStore(f"sqlite+aiosqlite:///{path}")
    try:
        with pytest.raises(ValueError):
            await migrate(store)
        async with store.engine.connect() as conn:
            names = await conn.run_sync(lambda c: inspect(c).get_table_names())
        assert sorted(names) == ["payments", "users"]
    finally:
        await store.close()


async def test_trial_only_legacy_schema_is_supported(tmp_path):
    path = tmp_path / "trial.db"
    with sqlite3.connect(path) as conn:
        conn.executescript("""
            CREATE TABLE trial_users (telegram_id INTEGER, uuid TEXT, email TEXT, port INTEGER,
                                      expiry_time INTEGER, short_id TEXT);
            INSERT INTO trial_users VALUES (1, 'uuid', '1234567', 12000, 1800000000000, 'short');
        """)
    store = SQLStore(f"sqlite+aiosqlite:///{path}")
    try:
        await migrate(store)
        subscription = await store.subscription(1)
        assert subscription.devices == 1
        assert subscription.sub_id == "trial_234567"
    finally:
        await store.close()


async def test_legacy_import_handles_null_ip_limit_and_is_active(tmp_path):
    path = tmp_path / "nulls.db"
    with sqlite3.connect(path) as conn:
        conn.executescript("""
            CREATE TABLE users (telegram_id INTEGER PRIMARY KEY, uuid TEXT, email TEXT,
                port INTEGER, expiry_time INTEGER, ip_limit INTEGER, short_id TEXT, is_active BOOLEAN);
            INSERT INTO users VALUES (10, 'uuid-null', 'mail1234', 12001, 1800000000000, NULL, 'short-null', NULL);
        """)
    store = SQLStore(f"sqlite+aiosqlite:///{path}")
    try:
        result = await migrate(store)
        assert result["subscriptions"] == 1
        subscription = await store.subscription(10)
        assert subscription.devices == 1
        assert subscription.enabled is True
    finally:
        await store.close()
