"""Модуль для работы с базой данных SQLite"""
import logging
import aiosqlite
from datetime import datetime
from config import DB_PATH


async def init_db():
    """Создает таблицу для хранения пользователей, если её нет"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS trial_users (
                telegram_id INTEGER PRIMARY KEY,
                uuid TEXT NOT NULL,
                email TEXT NOT NULL,
                port INTEGER NOT NULL,
                public_key TEXT NOT NULL,
                expiry_time INTEGER NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        await db.commit()
        logging.info("✅ База данных инициализирована")


async def user_exists(telegram_id: int) -> bool:
    """Проверяет, существует ли пользователь с таким telegram_id в базе"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT 1 FROM trial_users WHERE telegram_id = ?",
                (telegram_id,)
            ) as cursor:
                row = await cursor.fetchone()
                return row is not None
    except Exception as e:
        logging.error(f"❌ Ошибка при проверке пользователя: {e}")
        return False


async def save_user(telegram_id: int, uuid: str, email: str, port: int, 
                   public_key: str, expiry_time: int):
    """Сохраняет данные пользователя в базу данных"""
    try:
        created_at = datetime.now().isoformat()
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                INSERT INTO trial_users 
                (telegram_id, uuid, email, port, public_key, expiry_time, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (telegram_id, uuid, email, port, public_key, expiry_time, created_at))
            await db.commit()
            logging.info(f"✅ Пользователь {telegram_id} сохранен в БД")
    except Exception as e:
        logging.error(f"❌ Ошибка при сохранении пользователя: {e}")

