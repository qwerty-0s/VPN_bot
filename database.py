"""Модуль для работы с базой данных SQLite"""
import logging
import aiosqlite
import json
from datetime import datetime
from config import DB_PATH


async def init_db():
    """
    Инициализирует базу данных с новой структурой.
    Создает таблицы users и payments.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        # Таблица users для всех пользователей (пробные и платные)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                telegram_id INTEGER PRIMARY KEY,
                uuid TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                port INTEGER UNIQUE NOT NULL,
                expiry_time INTEGER NOT NULL,
                ip_limit INTEGER NOT NULL DEFAULT 1,
                short_id TEXT UNIQUE NOT NULL,
                is_active BOOLEAN DEFAULT 1,
                warning_sent BOOLEAN DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        
        # Таблица payments для отслеживания платежей
        await db.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                payment_id TEXT UNIQUE NOT NULL,
                telegram_id INTEGER NOT NULL,
                amount INTEGER NOT NULL,
                status TEXT DEFAULT 'pending',
                tariff_data TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (telegram_id) REFERENCES users(telegram_id)
            )
        """)
        
        # Индексы для оптимизации
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_users_telegram_id 
            ON users(telegram_id)
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_users_short_id 
            ON users(short_id)
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_payments_payment_id 
            ON payments(payment_id)
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_payments_telegram_id 
            ON payments(telegram_id)
        """)
        
        await db.commit()
        logging.info("✅ База данных инициализирована (новая структура)")


async def user_exists(telegram_id: int) -> bool:
    """Проверяет, существует ли пользователь с таким telegram_id в базе"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT 1 FROM users WHERE telegram_id = ?",
                (telegram_id,)
            ) as cursor:
                row = await cursor.fetchone()
                return row is not None
    except Exception as e:
        logging.error(f"❌ Ошибка при проверке пользователя: {e}")
        return False


async def save_user(telegram_id: int, uuid: str, email: str, port: int,
                   expiry_time: int, short_id: str, ip_limit: int = 1,
                   is_active: bool = True):
    """
    Сохраняет или обновляет данные пользователя в базу данных.
    
    Args:
        telegram_id: ID пользователя в Telegram
        uuid: VLESS UUID
        email: Email в формате tg_123456
        port: Порт подключения
        expiry_time: Unix timestamp (ms) окончания подписки
        short_id: Короткий идентификатор подписки
        ip_limit: Лимит устройств (по умолчанию 1 для пробных)
        is_active: Активна ли подписка (по умолчанию True)
    """
    try:
        now = datetime.now().isoformat()
        async with aiosqlite.connect(DB_PATH) as db:
            # Пытаемся обновить существующего пользователя
            await db.execute("""
                INSERT OR REPLACE INTO users
                (telegram_id, uuid, email, port, expiry_time, ip_limit, short_id, 
                 is_active, warning_sent, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
            """, (telegram_id, uuid, email, port, expiry_time, ip_limit, 
                  short_id, is_active, now, now))
            await db.commit()
            logging.info(f"✅ Пользователь {telegram_id} сохранен в БД")
    except Exception as e:
        logging.error(f"❌ Ошибка при сохранении пользователя: {e}")


async def get_user_by_telegram_id(telegram_id: int):
    """
    Возвращает запись пользователя по telegram_id.
    
    Returns:
        dict с полями: telegram_id, uuid, email, port, expiry_time, ip_limit, 
                       short_id, is_active, warning_sent, created_at, updated_at
    """
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM users WHERE telegram_id = ?",
                (telegram_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return dict(row)
                return None
    except Exception as e:
        logging.error(f"❌ Ошибка при поиске пользователя по telegram_id: {e}")
        return None


async def get_user_by_short_id(short_id: str):
    """
    Возвращает запись пользователя по short_id.
    
    Returns:
        dict с полями пользователя или None
    """
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM users WHERE short_id = ?",
                (short_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return dict(row)
                return None
    except Exception as e:
        logging.error(f"❌ Ошибка при поиске пользователя по short_id: {e}")
        return None


async def get_user_by_email(email: str):
    """
    Возвращает запись пользователя по email.
    
    Returns:
        dict с полями пользователя или None
    """
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM users WHERE email = ?",
                (email,)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return dict(row)
                return None
    except Exception as e:
        logging.error(f"❌ Ошибка при поиске пользователя по email: {e}")
        return None


async def update_user(telegram_id: int, **kwargs):
    """
    Обновляет данные пользователя.
    
    Args:
        telegram_id: ID пользователя
        **kwargs: Поля для обновления (expiry_time, ip_limit, is_active и т.д.)
    """
    try:
        now = datetime.now().isoformat()
        
        # Формируем SET часть запроса динамически
        allowed_fields = {'expiry_time', 'ip_limit', 'is_active', 'warning_sent', 'uuid', 'email', 'port', 'short_id'}
        update_fields = {k: v for k, v in kwargs.items() if k in allowed_fields}
        
        if not update_fields:
            logging.warning(f"⚠️ Нет валидных полей для обновления у пользователя {telegram_id}")
            return
        
        # Всегда обновляем updated_at
        update_fields['updated_at'] = now
        
        set_clause = ", ".join([f"{k} = ?" for k in update_fields.keys()])
        values = list(update_fields.values()) + [telegram_id]
        
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                f"UPDATE users SET {set_clause} WHERE telegram_id = ?",
                values
            )
            await db.commit()
            logging.info(f"✅ Пользователь {telegram_id} обновлен: {update_fields}")
    except Exception as e:
        logging.error(f"❌ Ошибка при обновлении пользователя: {e}")


async def disable_user(telegram_id: int):
    """Отключает пользователя (is_active = 0)"""
    await update_user(telegram_id, is_active=False)
    logging.info(f"✅ Пользователь {telegram_id} отключен")


async def activate_user(telegram_id: int):
    """Активирует пользователя (is_active = 1)"""
    await update_user(telegram_id, is_active=True)
    logging.info(f"✅ Пользователь {telegram_id} активирован")


async def set_warning_sent(telegram_id: int, sent: bool = True):
    """Устанавливает флаг warning_sent для пользователя"""
    await update_user(telegram_id, warning_sent=sent)


async def get_users_expiring_soon(hours: int = 24):
    """
    Возвращает пользователей, у которых подписка истекает через N часов.
    
    Args:
        hours: Количество часов до истечения
        
    Returns:
        list of dicts с пользователями
    """
    try:
        import time
        threshold = int(time.time() * 1000) + (hours * 3600 * 1000)
        
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT * FROM users 
                WHERE is_active = 1 AND warning_sent = 0 
                AND expiry_time < ? AND expiry_time > ?
            """, (threshold, int(time.time() * 1000))) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
    except Exception as e:
        logging.error(f"❌ Ошибка при поиске пользователей с истекающей подпиской: {e}")
        return []


async def get_expired_users():
    """
    Возвращает пользователей с истекшей подпиской.
    
    Returns:
        list of dicts с пользователями
    """
    try:
        import time
        now = int(time.time() * 1000)
        
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT * FROM users 
                WHERE is_active = 1 AND expiry_time <= ?
            """, (now,)) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
    except Exception as e:
        logging.error(f"❌ Ошибка при поиске истекших подписок: {e}")
        return []


# ============================================================================
# PAYMENT-related functions
# ============================================================================

async def save_payment(payment_id: str, telegram_id: int, amount: int, 
                      tariff_data: dict, status: str = 'pending'):
    """
    Сохраняет информацию о платеже.
    
    Args:
        payment_id: ID платежа в системе ЮKassa
        telegram_id: ID пользователя
        amount: Сумма платежа в копейках
        tariff_data: dict с {days, devices} или другими параметрами тарифа
        status: Статус платежа (pending, succeeded, canceled)
    """
    try:
        now = datetime.now().isoformat()
        tariff_json = json.dumps(tariff_data) if isinstance(tariff_data, dict) else tariff_data
        
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                INSERT INTO payments 
                (payment_id, telegram_id, amount, status, tariff_data, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (payment_id, telegram_id, amount, status, tariff_json, now, now))
            await db.commit()
            logging.info(f"✅ Платеж {payment_id} сохранен для пользователя {telegram_id}")
    except Exception as e:
        logging.error(f"❌ Ошибка при сохранении платежа: {e}")


async def get_payment_by_id(payment_id: str):
    """
    Возвращает информацию о платеже по payment_id.
    
    Returns:
        dict с полями платежа или None
    """
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM payments WHERE payment_id = ?",
                (payment_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    payment = dict(row)
                    # Парсим JSON из tariff_data
                    try:
                        payment['tariff_data'] = json.loads(payment['tariff_data'])
                    except:
                        pass
                    return payment
                return None
    except Exception as e:
        logging.error(f"❌ Ошибка при получении платежа: {e}")
        return None


async def update_payment(payment_id: str, status: str):
    """
    Обновляет статус платежа.
    
    Args:
        payment_id: ID платежа
        status: Новый статус (pending, succeeded, canceled)
    """
    try:
        now = datetime.now().isoformat()
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE payments SET status = ?, updated_at = ? WHERE payment_id = ?",
                (status, now, payment_id)
            )
            await db.commit()
            logging.info(f"✅ Статус платежа {payment_id} обновлен: {status}")
    except Exception as e:
        logging.error(f"❌ Ошибка при обновлении платежа: {e}")


async def get_user_payments(telegram_id: int):
    """
    Возвращает все платежи пользователя.
    
    Returns:
        list of dicts с платежами
    """
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM payments WHERE telegram_id = ? ORDER BY created_at DESC",
                (telegram_id,)
            ) as cursor:
                rows = await cursor.fetchall()
                payments = []
                for row in rows:
                    payment = dict(row)
                    try:
                        payment['tariff_data'] = json.loads(payment['tariff_data'])
                    except:
                        pass
                    payments.append(payment)
                return payments
    except Exception as e:
        logging.error(f"❌ Ошибка при получении платежей пользователя: {e}")
        return []
