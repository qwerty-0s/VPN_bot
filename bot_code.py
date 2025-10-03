import asyncio
import logging
from aiogram import Bot, Dispatcher, F, types
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web
import ssl
import aiohttp

# -------------------
# 🔹 Конфиг
# -------------------
API_TOKEN = "8290944633:AAG9FTaFvpkJiTF89N9u-WhW_puypYIqf30"
WEBHOOK_URL = "https://v460023.hosted-by-vdsina.com/webhook"
WEBAPP_HOST = "127.0.0.1"
WEBAPP_PORT = 8443

# 🔹 Настройки 3x-ui
XUI_API = "https://127.0.0.1:33465/7HWmi6anA3YCrCOtWf"
XUI_USER = "Gena"
XUI_PASS = "Tranzisto1"

# -------------------
# 🔹 Telegram бот
# -------------------
bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# Храним aiohttp-сессию глобально
xui_session: aiohttp.ClientSession | None = None


# -------------------
# 🔹 Эхо-обработчик
# -------------------
#@dp.message(F.text)
#async def echo_handler(message: types.Message):
#    await message.answer(f"Ты написал: {message.text}")
    
    
# обрабочтик /users 
@dp.message(F.text == "/users")
async def users_handler(message: types.Message):
    users = await get_users()
    if not users:
        await message.answer("❌ Не удалось получить список пользователей")
        return

    # Для красоты формируем текст
    reply_text = "📋 Список пользователей:\n\n"
    if isinstance(users, dict) and "obj" in users:  
        # Обычно список лежит в users["obj"]
        for user in users["obj"]:
            remark = user.get("remark", "—")
            enable = "✅" if user.get("enable") else "❌"
            reply_text += f"{enable} {remark}\n"
    else:
        reply_text += str(users)

    await message.answer(reply_text)


# -------------------
# 🔹 Авторизация в 3x-ui
# -------------------
async def get_xui_session():
    """Логинимся в 3x-ui и возвращаем aiohttp.ClientSession с куками"""
    global xui_session

    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE

    session = aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar())
    try:
        async with session.post(
            f"{XUI_API}/login",
            json={"username": XUI_USER, "password": XUI_PASS},
            ssl=ssl_context
        ) as resp:
            text = await resp.text()
            logging.info(f"Ответ сервера 3x-ui: {text}")
            data = await resp.json(content_type=None)

            if data.get("success"):
                logging.info("✅ Успешный вход в 3x-ui, куки сохранены")
                xui_session = session
            else:
                logging.error(f"❌ Ошибка входа: {data}")
                await session.close()
                xui_session = None
    except Exception as e:
        logging.error(f"❌ Ошибка при соединении с 3x-ui: {e}")
        await session.close()
        xui_session = None


async def get_users():
    """Пример: получаем список пользователей из 3x-ui"""
    global xui_session
    if not xui_session:
        logging.error("❌ Нет активной сессии для запросов к 3x-ui")
        return None

    try:
        async with xui_session.post(f"{XUI_API}/panel/api/inbounds/list") as resp:
            text = await resp.text()
            logging.info(f"📥 Ответ на list: {text}")
            data = await resp.json(content_type=None)
            return data
    except Exception as e:
        logging.error(f"❌ Ошибка при получении пользователей: {e}")
        return None
    



# -------------------
# 🔹 Жизненный цикл
# -------------------
async def on_startup(app: web.Application):
    await bot.set_webhook(WEBHOOK_URL)
    await get_xui_session()  # логинимся в 3x-ui


async def on_shutdown(app: web.Application):
    await bot.delete_webhook()
    global xui_session
    if xui_session:
        await xui_session.close()


# -------------------
# 🔹 Точка входа
# -------------------
def main():
    logging.basicConfig(level=logging.INFO)
    app = web.Application()
    SimpleRequestHandler(dp, bot).register(app, path="/webhook")
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)
    setup_application(app, dp, bot=bot)
    web.run_app(app, host=WEBAPP_HOST, port=WEBAPP_PORT)


if __name__ == "__main__":
    main()
