"""Главный файл запуска бота"""
import logging

from aiogram import Bot, Dispatcher
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

from config import API_TOKEN, WEBHOOK_URL, WEBAPP_HOST, WEBAPP_PORT
from database import init_db
from xui_api import get_xui_cookie
from handlers import register_handlers
from web_routes import handle_short_sub, handle_yookassa_webhook

# Инициализация бота и диспетчера
bot = Bot(token=API_TOKEN)
dp = Dispatcher()

register_handlers(dp)


async def on_startup(app: web.Application):
    """Действия при запуске приложения."""
    await init_db()
    await bot.set_webhook(WEBHOOK_URL)
    await get_xui_cookie()
    logging.info("✅ Бот запущен, вебхук установлен")


async def on_shutdown(app: web.Application):
    """Действия при остановке приложения."""
    await bot.delete_webhook()
    logging.info("🛑 Вебхук удалён")


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    app = web.Application()

    # Передаём bot в app чтобы web_routes мог отправлять сообщения пользователям
    app["bot"] = bot

    # Telegram webhook
    SimpleRequestHandler(dp, bot).register(app, path="/webhook")

    # Подписки VPN
    app.router.add_get("/sub/{short_id}", handle_short_sub)

    # ЮKassa webhook
    # URL необходимо зарегистрировать в личном кабинете ЮKassa:
    # https://<ваш домен>/yookassa-webhook
    app.router.add_post("/yookassa-webhook", handle_yookassa_webhook)

    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)

    setup_application(app, dp, bot=bot)

    logging.info(f"🚀 Запуск на {WEBAPP_HOST}:{WEBAPP_PORT}")
    web.run_app(app, host=WEBAPP_HOST, port=WEBAPP_PORT)


if __name__ == "__main__":
    main()