# Миграция на модульную структуру

Бот был разделен на модули для лучшей организации кода.

## Что изменилось

### Старая структура
- `bot_code.py` - один файл со всем кодом

### Новая структура
- `main.py` - точка входа
- `config.py` - конфигурация из .env
- `database.py` - работа с БД
- `xui_api.py` - API XUI
- `handlers.py` - обработчики сообщений

## Миграция

1. **Создайте файл `.env`** в директории `VPN_bot/`:
```bash
cd VPN_bot
nano .env
```

Заполните следующими данными (замените на свои):
```
API_TOKEN=8290944633:AAG9FTaFvpkJiTF89N9u-WhW_puypYIqf30
WEBHOOK_URL=https://v460023.hosted-by-vdsina.com/webhook
WEBAPP_HOST=127.0.0.1
WEBAPP_PORT=8443
XUI_API=https://109.234.34.215:33465/7HWmi6anA3YCrCOtWf
XUI_USER=Gena
XUI_PASS=Tranzisto1
VPN_DOMAIN=109.234.34.215
DB_PATH=vpn_bot.db
```

2. **Установите зависимости**:
```bash
pip install -r requirements.txt
```

3. **Запустите бота**:
```bash
python main.py
```

## Старый файл

Файл `bot_code.py` можно оставить для справки или удалить после проверки работы нового кода.

