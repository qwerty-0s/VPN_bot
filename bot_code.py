import asyncio
import logging
from aiogram import Bot, Dispatcher, F, types
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web, ClientSession

# -------------------
# 🔹 Конфиг
# -------------------
API_TOKEN = "8290944633:AAG9FTaFvpkJiTF89N9u-WhW_puypYIqf30"
WEBHOOK_URL = "https://v460023.hosted-by-vdsina.com/webhook"  # тот же путь, что в nginx
WEBAPP_HOST = "127.0.0.1"
WEBAPP_PORT = 8443  # должен совпадать с proxy_pass в nginx

# 🔹 Настройки 3x-ui
XUI_API = "http://127.0.0.1:2053"   # панель 3x-ui, может быть другой порт
XUI_USER = "Gena"                  # логин от панели
XUI_PASS = "Tranzisto1"          # пароль от панели
xui_token = None                    # будем хранить токен здесь

# -------------------
# 🔹 Telegram бот
# -------------------
bot = Bot(token=API_TOKEN)
dp = Dispatcher()


# Эхо-обработчик
@dp.message(F.text)
async def echo_handler(message: types.Message):
    await message.answer(f"Ты написал: {message.text}")


# -------------------
# 🔹 Авторизация в 3x-ui
# -------------------
async def get_xui_token():
    """Получаем accessToken у 3x-ui"""
    global xui_token
    async with ClientSession() as session:
        async with session.post(f"{XUI_API}/login",
                                json={"username": XUI_USER, "password": XUI_PASS}) as resp:
            data = await resp.json()
            if data.get("success"):
                xui_token = data["accessToken"]
                logging.info("✅ Получен токен 3x-ui")
            else:
                logging.error(f"❌ Ошибка входа в 3x-ui: {data}")


# -------------------
# 🔹 Жизненный цикл
# -------------------
async def on_startup(app: web.Application):
    await bot.set_webhook(WEBHOOK_URL)
    await get_xui_token()


async def on_shutdown(app: web.Application):
    await bot.delete_webhook()


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
