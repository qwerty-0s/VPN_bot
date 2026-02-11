# 🔧 КРИТИЧЕСКИЕ РЕШЕНИЯ - Примеры Кода

> Этот файл содержит готовые примеры кода для исправления критических проблем

---

## 1️⃣ ГОНКА В БД (Критичная)

### ❌ ТЕКУЩЕЕ (НЕПРАВИЛЬНОЕ):
```python
# handlers.py, строка ~372
result = await create_trial_inbound(telegram_id)
# ... создание в XUI ...

# ПЛОХО: магический sleep!
import asyncio
await asyncio.sleep(0.5)

user = await get_user_by_telegram_id(telegram_id)
if not user:
    logging.error("❌ Не удалось получить данные пользователя")
    return
```

### ✅ РЕШЕНИЕ 1: Lock-based (Рекомендуется)
```python
# models.py или utils.py - новый файл

import asyncio
from typing import Dict

class SubscriptionManager:
    """Менеджер для синхронизации создания подписок"""
    _locks: Dict[int, asyncio.Lock] = {}
    
    @classmethod
    def get_lock(cls, telegram_id: int) -> asyncio.Lock:
        """Получить lock для конкретного пользователя"""
        if telegram_id not in cls._locks:
            cls._locks[telegram_id] = asyncio.Lock()
        return cls._locks[telegram_id]

# В handlers.py:
async def trial_button(message: types.Message):
    telegram_id = message.from_user.id
    
    async with SubscriptionManager.get_lock(telegram_id):
        # ВСЕ операции создания подписки внутри lock
        user = await get_user_by_telegram_id(telegram_id)
        if user:
            await message.answer("⚠️ У вас уже есть подписка!")
            return
        
        result = await create_trial_inbound(telegram_id)
        if not result:
            await message.answer("❌ Ошибка создания подписки")
            return
        
        # БД уже обновлена внутри create_trial_inbound
        # Получаем заново БЕЗ sleep
        user = await get_user_by_telegram_id(telegram_id)
        if not user:
            # Это НЕ должно происходить если create правильна
            logging.error(f"❌ КРИТИЧНО: Данные не в БД после создания")
            return
        
        # Продолжаем с пользователем
        short_id = user.get('short_id')
        await send_instruction_with_images_message(message, short_id)
```

### ✅ РЕШЕНИЕ 2: Используя контекст менеджер (Альтернатива)
```python
# Создать файл: subscription_context.py

from contextlib import asynccontextmanager
from database import get_user_by_telegram_id
import logging

class SubscriptionContext:
    """Контекст для проверки что подписка создана корректно"""
    
    @staticmethod
    @asynccontextmanager
    async def create_and_verify(telegram_id: int, creation_func):
        """
        Создает подписку и гарантирует что она в БД
        
        Usage:
            async with SubscriptionContext.create_and_verify(tg_id, create_trial_inbound) as user:
                # user уже гарантированно в БД
        """
        # Создаем
        result = await creation_func(telegram_id)
        if not result or result.get("error"):
            raise Exception(f"Ошибка создания: {result}")
        
        # Проверяем макс 10 раз с backoff
        user = None
        for attempt in range(10):
            user = await get_user_by_telegram_id(telegram_id)
            if user:
                break
            # Exponential backoff: 10ms, 20ms, 40ms...
            await asyncio.sleep(0.01 * (2 ** attempt))
        
        if not user:
            logging.error(f"❌ КРИТИЧНО: Подписка не найдена в БД после 10 попыток")
            raise Exception("Подписка создана но не найдена в БД")
        
        try:
            yield user
        finally:
            # Очистка если нужна
            pass

# В handlers.py:
async def trial_button(message: types.Message):
    telegram_id = message.from_user.id
    
    async with SubscriptionManager.get_lock(telegram_id):
        try:
            async with SubscriptionContext.create_and_verify(
                telegram_id, 
                create_trial_inbound
            ) as user:
                short_id = user.get('short_id')
                await send_instruction_with_images_message(message, short_id)
        except Exception as e:
            logging.error(f"❌ Ошибка: {e}")
            await message.answer(f"❌ Ошибка при создании подписки: {str(e)}")
```

---

## 2️⃣ ОБРАБОТКА ОШИБОК XUI API

### ❌ ТЕКУЩЕЕ (НЕПРАВИЛЬНОЕ):
```python
# xui_api.py
result = await create_trial_inbound(telegram_id)

if not result or result.get("error"):
    await message.answer("❌ Не удалось создать пробную подписку.")
    # Пользователь не знает почему!
```

### ✅ РЕШЕНИЕ: Детальная обработка с retry
```python
# Добавить в xui_api.py:

import asyncio
from enum import Enum
from typing import Optional, Tuple

class XUIError(Enum):
    """Типы ошибок XUI API"""
    TIMEOUT = "timeout"
    AUTH_FAILED = "auth_failed"
    NO_FREE_PORT = "no_free_port"
    INVALID_RESPONSE = "invalid_response"
    API_ERROR = "api_error"
    NETWORK_ERROR = "network_error"
    UNKNOWN = "unknown"

class XIUCreateError(Exception):
    """Исключение при создании подписки в XUI"""
    def __init__(self, error_type: XUIError, message: str, retry_after: int = 0):
        self.error_type = error_type
        self.message = message
        self.retry_after = retry_after
        super().__init__(message)

async def create_trial_inbound_with_retry(telegram_id: int, max_retries: int = 3) -> Tuple[bool, dict]:
    """
    Создает подписку с retry-логикой и детальной обработкой ошибок
    
    Returns:
        (success: bool, result: dict)
        result содержит либо данные подписки, либо информацию об ошибке
    """
    
    error_messages = {
        XUIError.TIMEOUT: "⏱️ Сервер долго отвечает. Попробуйте позже.",
        XUIError.AUTH_FAILED: "🔐 Ошибка доступа к панели VPN. Свяжитесь с /support",
        XUIError.NO_FREE_PORT: "🚫 Все порты заняты. Попробуйте позже.",
        XUIError.INVALID_RESPONSE: "📡 Странный ответ от сервера. Попробуйте позже.",
        XUIError.API_ERROR: "⚠️ Ошибка API. Попробуйте позже.",
        XUIError.NETWORK_ERROR: "🌐 Проблема с сетью. Попробуйте позже.",
        XUIError.UNKNOWN: "❓ Неизвестная ошибка. Свяжитесь с /support"
    }
    
    for attempt in range(max_retries):
        try:
            logging.info(f"🔄 Попытка {attempt + 1}/{max_retries} создания подписки {telegram_id}")
            
            # Проверка существования
            if await user_exists(telegram_id):
                return False, {
                    "error": "already_exists",
                    "message": "⚠️ У вас уже есть подписка"
                }
            
            # Получение cookie
            if not xui_cookie:
                await get_xui_cookie()
                if not xui_cookie:
                    raise XIUCreateError(XUIError.AUTH_FAILED, "Не удалось получить cookie")
            
            # Получение ключей
            keys = await asyncio.wait_for(
                get_new_reality_keys(),
                timeout=10.0  # 10 секунд таймаут
            )
            if not keys or "obj" not in keys:
                raise XIUCreateError(XUIError.INVALID_RESPONSE, "Неверный ответ при получении ключей")
            
            # Получение портов
            port = await asyncio.wait_for(
                get_free_port(),
                timeout=10.0
            )
            if not port:
                raise XIUCreateError(XUIError.NO_FREE_PORT, "Нет свободных портов")
            
            # Создание в БД
            private_key = keys["obj"]["privateKey"]
            short_key = keys["obj"]["shortIds"][0]
            
            # ... остальная логика создания ...
            
            logging.info(f"✅ Подписка {telegram_id} создана успешно")
            return True, {"success": True, "short_id": short_id}
            
        except asyncio.TimeoutError:
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt  # 1, 2, 4 сек
                logging.warning(f"⏱️ Таймаут на попытке {attempt + 1}, ждем {wait_time}сек")
                await asyncio.sleep(wait_time)
            else:
                return False, {
                    "error": "timeout_exceeded",
                    "message": error_messages[XUIError.TIMEOUT]
                }
        
        except XIUCreateError as e:
            if attempt < max_retries - 1 and e.error_type in [XUIError.TIMEOUT, XUIError.NETWORK_ERROR]:
                wait_time = 2 ** attempt
                logging.warning(f"⚠️ {e.message} на попытке {attempt + 1}, ждем {wait_time}сек")
                await asyncio.sleep(wait_time)
            else:
                return False, {
                    "error": e.error_type.value,
                    "message": error_messages.get(e.error_type, error_messages[XUIError.UNKNOWN])
                }
        
        except Exception as e:
            logging.error(f"❌ Неожиданная ошибка на попытке {attempt + 1}: {e}", exc_info=True)
            if attempt < max_retries - 1:
                await asyncio.sleep(1)
            else:
                return False, {
                    "error": "unknown",
                    "message": error_messages[XUIError.UNKNOWN]
                }
    
    return False, {
        "error": "max_retries_exceeded",
        "message": "❌ Не удалось создать подписку после нескольких попыток. Попробуйте позже."
    }

# В handlers.py использование:
async def trial_button(message: types.Message):
    telegram_id = message.from_user.id
    
    async with SubscriptionManager.get_lock(telegram_id):
        success, result = await create_trial_inbound_with_retry(telegram_id)
        
        if not success:
            error_message = result.get("message", "❌ Неизвестная ошибка")
            await message.answer(error_message)
            logging.warning(f"⚠️ Ошибка создания подписки {telegram_id}: {result['error']}")
            return
        
        short_id = result.get("short_id")
        await send_instruction_with_images_message(message, short_id)
```

---

## 3️⃣ ОБРАБОТКА ОТКЛЮЧЕНИЙ БД

### ❌ ТЕКУЩЕЕ (НЕПРАВИЛЬНОЕ):
```python
# database.py
async with aiosqlite.connect(DB_PATH) as db:
    await db.execute(...) 
    # Если БД заблокирована → Exception, бот падает
```

### ✅ РЕШЕНИЕ: Retry с таймаутом
```python
# Добавить в database.py:

import sqlite3
from tenacity import retry, stop_after_attempt, wait_exponential

async def save_user_with_retry(
    telegram_id: int, 
    uuid: str, 
    email: str,
    port: int,
    expiry_time: int,
    short_id: str,
    ip_limit: int = 1,
    is_active: bool = True,
    inbound_id: int = None
) -> bool:
    """
    Сохраняет пользователя с retry-логикой при блокировке БД
    
    Returns: True если успешно, False если не удалось
    """
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            now = datetime.now().isoformat()
            
            # Используем таймаут для соединения
            async with aiosqlite.connect(DB_PATH, timeout=10.0) as db:
                await db.execute("""
                    INSERT OR REPLACE INTO users
                    (telegram_id, uuid, email, port, expiry_time, ip_limit, 
                     short_id, is_active, warning_sent, inbound_id, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)
                """, (telegram_id, uuid, email, port, expiry_time, ip_limit,
                      short_id, is_active, inbound_id, now, now))
                
                await db.commit()
                logging.info(f"✅ Пользователь {telegram_id} сохранен в БД")
                return True
            
        except sqlite3.OperationalError as e:
            if "database is locked" in str(e):
                if attempt < max_retries - 1:
                    wait_time = 0.5 * (2 ** attempt)  # 0.5s, 1s, 2s
                    logging.warning(f"⚠️ БД заблокирована (попытка {attempt + 1}), жду {wait_time}s")
                    await asyncio.sleep(wait_time)
                    continue
                else:
                    logging.error(f"❌ БД заблокирована после {max_retries} попыток")
                    return False
            else:
                logging.error(f"❌ Ошибка БД: {e}")
                return False
        
        except sqlite3.IntegrityError as e:
            if "UNIQUE constraint failed: users.email" in str(e):
                logging.error(f"⚠️ Email уже существует: {email}")
            elif "UNIQUE constraint failed: users.uuid" in str(e):
                logging.error(f"⚠️ UUID уже существует: {uuid}")
            elif "UNIQUE constraint failed: users.port" in str(e):
                logging.error(f"⚠️ Port уже занят: {port}")
            else:
                logging.error(f"❌ Ошибка целостности: {e}")
            return False
        
        except Exception as e:
            logging.error(f"❌ Неожиданная ошибка при сохранении: {e}", exc_info=True)
            return False
    
    logging.error(f"❌ Не удалось сохранить пользователя {telegram_id} после {max_retries} попыток")
    return False

# Обновить функцию save_user чтобы использовать новую:
async def save_user(...):
    """Устаревшая функция - используйте save_user_with_retry"""
    return await save_user_with_retry(...)
```

---

## 4️⃣ ВАЛИДАЦИЯ ИНСТРУКЦИЙ

### ❌ ТЕКУЩЕЕ (НЕПРАВИЛЬНОЕ):
```python
# handlers.py
if os.path.exists(instr1_path):
    await callback.message.answer_photo(...)
else:
    logging.warning(f"⚠️ Файл {instr1_path} не найдено")
    # Функция сворачивается и продолжает - ПЛОХО!
```

### ✅ РЕШЕНИЕ: Строгая валидация
```python
# Добавить в handlers.py:

REQUIRED_INSTRUCTION_FILES = [
    'Instruction1.jpg',
    'Instruction2.jpg'
]

async def validate_instruction_files() -> Tuple[bool, List[str]]:
    """
    Проверяет наличие всех требуемых файлов инструкций
    
    Returns:
        (all_exist: bool, missing_files: List[str])
    """
    missing = []
    for filename in REQUIRED_INSTRUCTION_FILES:
        if not os.path.exists(filename):
            missing.append(filename)
    
    return len(missing) == 0, missing

async def notify_admin_critical(message: str):
    """Отправить критичное уведомление админу"""
    try:
        ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
        if ADMIN_ID:
            await bot.send_message(
                ADMIN_ID,
                f"🚨 КРИТИЧНО: {message}",
                parse_mode="HTML"
            )
    except Exception as e:
        logging.error(f"❌ Не удалось отправить админ-уведомление: {e}")

async def send_instruction_with_images_safe(callback, user_short_id: str) -> bool:
    """
    Отправляет инструкции с полной валидацией
    
    Returns: True если все успешно, False если ошибка
    """
    
    # 1. Валидация файлов
    all_exist, missing = await validate_instruction_files()
    
    if not all_exist:
        error_msg = f"ОТСУТСТВУЮТ ИНСТРУКЦИИ: {', '.join(missing)}"
        logging.error(f"❌ {error_msg}")
        
        # Уведомляем админа
        await notify_admin_critical(error_msg)
        
        # Отправляем пользователю
        try:
            await callback.message.answer(
                "⚠️ Временное техническое затруднение. "
                "Инструкции будут отправлены позже. "
                "Свяжитесь с /support если возникнут вопросы.",
                reply_markup=get_back_to_menu_keyboard()
            )
        except Exception as e:
            logging.error(f"❌ Не удалось отправить сообщение об ошибке: {e}")
        
        return False
    
    try:
        # 2. Отправляем первое изображение
        await callback.message.answer_photo(
            types.FSInputFile('Instruction1.jpg'),
            caption="📱 Инструкция подключения - Часть 1"
        )
        logging.info("✅ Первое изображение инструкции отправлено")
        
        # 3. Отправляем второе изображение
        await callback.message.answer_photo(
            types.FSInputFile('Instruction2.jpg'),
            caption="📱 Инструкция подключения - Часть 2"
        )
        logging.info("✅ Второе изображение инструкции отправлено")
        
        # 4. Отправляем ссылку и текст
        if user_short_id:
            link = f"https://{FRONT_DOMAIN}/sub/{user_short_id}"
            text = (
                "✅ *Подписка активирована!*\n\n"
                "🔗 Ваша ссылка на подписку:\n"
                f"`{link}`\n\n"
                "📌 *Шаги подключения:*\n"
                "1️⃣ Нажмите на ссылку и она скопируется в буффер обмена\n"
                "2️⃣ Вставьте ссылку в HAPP или любой другой VPN клиент\n"
                "3️⃣ Подключитесь к VPN и готово! 🎉"
            )
            await callback.message.answer(text, parse_mode="Markdown")
            logging.info(f"✅ Инструкция и ссылка отправлены")
        
        return True
        
    except Exception as e:
        logging.error(f"❌ Ошибка при отправке инструкций: {e}", exc_info=True)
        
        # Уведомляем админа об ошибке отправки
        await notify_admin_critical(f"Ошибка отправки инструкций: {e}")
        
        try:
            await callback.message.answer(
                "⚠️ Не удалось отправить инструкции. "
                "Свяжитесь с /support"
            )
        except:
            pass
        
        return False
```

---

## 📌 ГДЕ ПРИМЕНИТЬ ЭТИ РЕШЕНИЯ

1. **solution_1_db_lock.py** → используйте вместо старого кода гонки
2. **solution_2_xui_errors.py** → используйте вместо старого xui_api.py для создания
3. **solution_3_db_retry.py** → обновите database.py
4. **solution_4_validation.py** → обновите handlers.py для отправки инструкций

**Примерный порядок внедрения:**
1. День 1: Гонка в БД (#2) + Обработка ошибок БД (#3)
2. День 1-2: Обработка ошибок XUI (#1)
3. День 2: Валидация инструкций (#4)

---

## ✅ ПРОВЕРОЧНЫЙ СПИСОК

- [ ] Добавлен SubscriptionManager для синхронизации
- [ ] Применен retry-механизм в create_trial_inbound_with_retry
- [ ] Обновлены все функции БД на версию с retry
- [ ] Добавлена валидация файлов инструкций
- [ ] Добавлены уведомления админу при критичных ошибках
- [ ] Протестировано создание пробной подписки
- [ ] Протестировано создание платной подписки
- [ ] Проверены обработчики ошибок XUI
- [ ] Проверены обработчики отключений БД
- [ ] Логирование всех критичных ошибок
