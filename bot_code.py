import asyncio
import logging
from aiogram import Bot, Dispatcher, F, types
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web
import aiohttp
import ssl

# -------------------
# 🔹 Конфиг
# -------------------
API_TOKEN = "8290944633:AAG9FTaFvpkJiTF89N9u-WhW_puypYIqf30"
WEBHOOK_URL = "https://v460023.hosted-by-vdsina.com/webhook"
WEBAPP_HOST = "127.0.0.1"
WEBAPP_PORT = 8443

XUI_API = "https://109.234.34.215:33465/7HWmi6anA3YCrCOtWf"
XUI_USER = "Gena"
XUI_PASS = "Tranzisto1"

# -------------------
# 🔹 Telegram бот
# -------------------
bot = Bot(token=API_TOKEN)
dp = Dispatcher()

xui_cookie = None  # сюда сохраним cookie вручную


# -------------------
# 🔹 Авторизация в 3x-ui
# -------------------
async def get_xui_cookie():
    """Логинимся и сохраняем cookie из заголовка Set-Cookie"""
    global xui_cookie

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{XUI_API}/login",
                json={"username": XUI_USER, "password": XUI_PASS},
                ssl=False,
                headers={"Content-Type": "application/json"}
            ) as resp:
                text = await resp.text()
                logging.info(f"Ответ на /login: {text}")
                set_cookie = resp.headers.get("Set-Cookie")
                if set_cookie:
                    # вырезаем только первую cookie до точки с запятой
                    cookie_value = set_cookie.split(";")[0]
                    xui_cookie = cookie_value
                    logging.info(f"✅ Сохранена cookie: {xui_cookie}")
                else:
                    logging.error("❌ Сервер не вернул Set-Cookie!")
                    xui_cookie = None
    except Exception as e:
        logging.error(f"❌ Ошибка при логине: {e}")
        xui_cookie = None


# -------------------
# 🔹 Получаем список пользователей
# -------------------
async def get_users():
    global xui_cookie
    if not xui_cookie:
        logging.error("❌ Нет cookie для запроса")
        return None

    try:
        headers = {
            "Content-Type": "application/json",
            "Cookie": xui_cookie,  # вставляем cookie вручную
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{XUI_API}/panel/api/inbounds/list",
                ssl=False,
                headers=headers
            ) as resp:
                text = await resp.text()
                logging.info(f"📥 Ответ API /panel/api/inbounds/list: {text}")
                try:
                    data = await resp.json(content_type=None)
                    return data
                except Exception:
                    return {"raw": text}
    except Exception as e:
        logging.error(f"❌ Ошибка при получении пользователей: {e}")
        return None


# -------------------
# 🔹 Команда /users
# -------------------
@dp.message(F.text == "/users")
async def users_handler(message: types.Message):
    users = await get_users()
    if not users:
        await message.answer("❌ Не удалось получить список пользователей.")
        return

    # Если не JSON
    if "raw" in users:
        await message.answer("⚠️ Ответ не JSON:\n" + users["raw"][:3000])
        return

    reply_text = "📋 Список пользователей:\n\n"
    if "obj" in users:
        for user in users["obj"]:
            remark = user.get("remark", "—")
            enable = "✅" if user.get("enable") else "❌"
            reply_text += f"{enable} {remark}\n"
    else:
        reply_text += str(users)

    await message.answer(reply_text)


# -------------------
# 🔹 Жизненный цикл
# -------------------
async def on_startup(app: web.Application):
    await bot.set_webhook(WEBHOOK_URL)
    await get_xui_cookie()  # получаем cookie при старте


async def on_shutdown(app: web.Application):
    await bot.delete_webhook()


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
