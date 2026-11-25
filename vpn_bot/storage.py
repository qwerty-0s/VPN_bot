"""SQLAlchemy implementation of the storage ports for SQLite and PostgreSQL."""

from contextlib import asynccontextmanager
from dataclasses import asdict

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    event,
    insert,
    inspect,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import create_async_engine

from .domain import Order, Subscription

metadata = MetaData()
schema = Table("vpn_schema", metadata, Column("version", Integer, primary_key=True))
accounts = Table(
    "vpn_accounts",
    metadata,
    Column("telegram_id", BigInteger, primary_key=True),
    Column("revision", BigInteger, nullable=False, default=0),
)
orders = Table(
    "vpn_orders",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("request_key", String(200), unique=True, nullable=False),
    Column("telegram_id", BigInteger, ForeignKey("vpn_accounts.telegram_id"), nullable=False),
    Column("amount", Integer, nullable=False),
    Column("days", Integer, nullable=False),
    Column("devices", Integer, nullable=False),
    Column("created_ms", BigInteger, nullable=False),
    Column("return_url", String(2048), nullable=False),
    Column("payment_id", String(100), unique=True),
    Column("confirmation_url", String(2048)),
    Column("status", String(30), nullable=False),
    Column("applied", Boolean, nullable=False),
    Column("legacy", Boolean, nullable=False),
    Column("notified", Boolean, nullable=False),
)
subscriptions = Table(
    "vpn_subscriptions",
    metadata,
    Column("telegram_id", BigInteger, ForeignKey("vpn_accounts.telegram_id"), primary_key=True),
    Column("uuid", String(36), unique=True, nullable=False),
    Column("email", String(200), unique=True, nullable=False),
    Column("short_id", String(100), unique=True, nullable=False),
    Column("sub_id", String(100), nullable=False),
    Column("expiry_ms", BigInteger, nullable=False),
    Column("devices", Integer, nullable=False),
    Column("port", Integer),
    Column("synced", Boolean, nullable=False),
    Column("enabled", Boolean, nullable=False),
)


async def one(conn, table, condition, model):
    row = (await conn.execute(select(table).where(condition))).mappings().first()
    return model(**row) if row else None


class SQLTransaction:
    def __init__(self, conn):
        self.conn = conn

    async def order(self, order_id):
        return await one(self.conn, orders, orders.c.id == order_id, Order)

    async def by_request(self, request_key):
        return await one(self.conn, orders, orders.c.request_key == request_key, Order)

    async def add_order(self, order):
        await self.conn.execute(insert(orders).values(**asdict(order)))

    async def save_order(self, order):
        await self.conn.execute(update(orders).where(orders.c.id == order.id).values(**asdict(order)))

    async def subscription(self, telegram_id):
        return await one(self.conn, subscriptions, subscriptions.c.telegram_id == telegram_id, Subscription)

    async def save_subscription(self, subscription):
        existing = await self.subscription(subscription.telegram_id)
        statement = (
            update(subscriptions).where(subscriptions.c.telegram_id == subscription.telegram_id)
            if existing
            else insert(subscriptions)
        )
        await self.conn.execute(statement.values(**asdict(subscription)))


class SQLStore:
    def __init__(self, url):
        if not url.startswith(("sqlite+aiosqlite:", "postgresql+asyncpg:")):
            raise ValueError("Use sqlite+aiosqlite or postgresql+asyncpg DATABASE_URL")
        self.engine = create_async_engine(url, pool_pre_ping=True)
        if self.engine.dialect.name == "sqlite":

            @event.listens_for(self.engine.sync_engine, "connect")
            def connect(dbapi_connection, _):
                # Explicit BEGIN also makes DDL/import rollback atomic on Python 3.10+.
                dbapi_connection.isolation_level = None
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute("PRAGMA busy_timeout=30000")
                cursor.close()

            @event.listens_for(self.engine.sync_engine, "begin")
            def begin(conn):
                conn.exec_driver_sql("BEGIN IMMEDIATE")

    async def initialize(self):
        async with self.engine.begin() as conn:
            names = await conn.run_sync(lambda c: inspect(c).get_table_names())
            if "vpn_schema" not in names and {"users", "payments", "trial_users"} & set(names):
                raise RuntimeError("Legacy database: back up and run python -m vpn_bot.migrate")
            await conn.run_sync(metadata.create_all)
            version = (await conn.execute(select(schema.c.version))).scalars().all()
            if not version:
                await conn.execute(insert(schema).values(version=1))
            elif version != [1]:
                raise RuntimeError("Unsupported database schema")

    @asynccontextmanager
    async def transaction(self, telegram_id):
        async with self.engine.begin() as conn:
            factory = sqlite_insert if conn.dialect.name == "sqlite" else pg_insert
            await conn.execute(
                factory(accounts)
                .values(telegram_id=telegram_id, revision=0)
                .on_conflict_do_nothing(index_elements=[accounts.c.telegram_id])
            )
            # Cross-process lock: row lock in PostgreSQL, writer lock in SQLite.
            await conn.execute(
                update(accounts)
                .where(accounts.c.telegram_id == telegram_id)
                .values(revision=accounts.c.revision + 1)
            )
            yield SQLTransaction(conn)

    async def _one(self, table, condition, model):
        async with self.engine.connect() as conn:
            return await one(conn, table, condition, model)

    async def order(self, order_id):
        return await self._one(orders, orders.c.id == order_id, Order)

    async def by_payment(self, payment_id):
        return await self._one(orders, orders.c.payment_id == payment_id, Order)

    async def subscription(self, telegram_id):
        return await self._one(subscriptions, subscriptions.c.telegram_id == telegram_id, Subscription)

    async def by_short_id(self, short_id):
        return await self._one(subscriptions, subscriptions.c.short_id == short_id, Subscription)

    async def pending_orders(self):
        async with self.engine.connect() as conn:
            rows = (
                await conn.execute(
                    select(orders)
                    .where(orders.c.status.in_(["creating", "pending", "waiting_for_capture"]))
                    .order_by(orders.c.created_ms)
                )
            ).mappings()
            return [Order(**row) for row in rows]

    async def unsynced(self):
        async with self.engine.connect() as conn:
            rows = (
                await conn.execute(select(subscriptions).where(subscriptions.c.synced.is_(False)))
            ).mappings()
            return [Subscription(**row) for row in rows]

    async def close(self):
        await self.engine.dispose()

    async def pending_notifications(self):
        async with self.engine.connect() as conn:
            rows = (
                await conn.execute(
                    select(orders).where(orders.c.applied.is_(True), orders.c.notified.is_(False))
                )
            ).mappings()
            return [Order(**row) for row in rows]
