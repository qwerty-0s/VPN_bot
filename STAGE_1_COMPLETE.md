## 📋 ЭТАП 1 - ЗАВЕРШЕН: Рефакторинг database.py и config.py

### ✅ Что было сделано:

#### 1. **config.py** - Добавлена тарифная сетка
- **TARIFFS**: Матрица 3 срока × 3 количества устройств
  - 1 месяц: 150₽ (1 устр.), 200₽ (3 устр.), 250₽ (5 устр.)
  - 3 месяца: 400₽ (1 устр.), 500₽ (3 устр.), 600₽ (5 устр.)
  - 6 месяцев: 700₽ (1 устр.), 850₽ (3 устр.), 1000₽ (5 устр.)
- Каждый тариф содержит: price, days, devices

#### 2. **database.py** - Полная миграция на новую структуру
Удалена таблица `trial_users`, созданы две новые:

##### **Таблица users**
```
telegram_id (INTEGER PK)     - ID пользователя в Telegram
uuid (TEXT)                 - VLESS UUID
email (TEXT UNIQUE)         - Формат: tg_123456
port (INTEGER UNIQUE)       - Порт подключения
expiry_time (INTEGER)       - Unix timestamp (ms) окончания подписки
ip_limit (INTEGER)          - Лимит устройств (1, 3, 5)
short_id (TEXT UNIQUE)      - ID для коротких ссылок подписки
is_active (BOOLEAN)         - Статус (1 = работает, 0 = отключен)
warning_sent (BOOLEAN)      - Флаг уведомления об окончании
created_at (TEXT)           - Дата создания
updated_at (TEXT)           - Дата обновления
```

##### **Таблица payments**
```
id (INTEGER PK)            - ID транзакции
payment_id (TEXT UNIQUE)   - ID в системе ЮKassa
telegram_id (INTEGER FK)   - ID плательщика
amount (INTEGER)           - Сумма платежа в копейках
status (TEXT)              - pending, succeeded, canceled
tariff_data (TEXT JSON)    - {days, devices}
created_at (TEXT)          - Дата создания
updated_at (TEXT)          - Дата обновления
```

##### **Добавленные функции:**
- `init_db()` - Инициализация новой структуры БД
- `user_exists(telegram_id)` - Проверка существования пользователя
- `save_user()` - Сохранение/обновление пользователя (INSERT OR REPLACE)
- `get_user_by_telegram_id(telegram_id)` - Получение пользователя
- `get_user_by_short_id(short_id)` - Получение по short_id (для ссылок)
- `get_user_by_email(email)` - Получение по email
- `update_user(telegram_id, **kwargs)` - Гибкое обновление полей
- `disable_user(telegram_id)` - Отключение подписки
- `activate_user(telegram_id)` - Активация подписки
- `set_warning_sent(telegram_id, sent)` - Установка флага уведомления
- `get_users_expiring_soon(hours)` - Поиск пользователей с истекающей подпиской
- `get_expired_users()` - Поиск просроченных подписок
- `save_payment(payment_id, telegram_id, amount, tariff_data, status)`
- `get_payment_by_id(payment_id)` - Получение платежа
- `update_payment(payment_id, status)` - Обновление статуса платежа
- `get_user_payments(telegram_id)` - История платежей пользователя

#### 3. **xui_api.py** - Обновлена функция создания пробной подписки
- `create_trial_inbound()` теперь использует новую функцию `save_user()`
- Пробная подписка: ip_limit=1, is_active=True (заданы по умолчанию)

#### 4. **web_routes.py** - Обновлена обработка коротких ссылок
- `handle_short_sub()` теперь работает с `get_user_by_short_id()` из новой БД
- Возвращает dict вместо tuple (для удобства)

#### 5. **handlers.py** - Полная совместимость
- Без изменений - использует `create_trial_inbound()` который совместим

#### 6. **main.py** - Полная совместимость
- Без изменений - использует `init_db()` который работает с новой структурой

### 📊 Статус совместимости:
- ✅ Пробная подписка - РАБОТАЕТ
- ✅ Коротки ссылки на подписку - РАБОТАЕТ
- ✅ Синтаксис всех файлов проверен
- ✅ Все функции базируются на новой структуре

### 🔄 Сохраненный функционал:
- ✅ Создание пробной подписки (3 дня)
- ✅ Коротки ссылки вида `/sub/{short_id}`
- ✅ Проксирование подписки через web_routes
- ✅ Список пользователей из XUI панели
- ✅ Главное меню и обработчики команд

### 📝 Готово к ЭТАПУ 2:
**Реализация модуля yookassa_pay.py** - Создание и проверка платежей через ЮKassa API
- Функция создания платежа
- Функция проверки статуса платежа
- Webhook обработчик для уведомлений
