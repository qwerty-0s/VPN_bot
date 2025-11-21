"""Главный файл запуска бота"""
import logging
from aiogram import Bot, Dispatcher
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web
from config import API_TOKEN, WEBHOOK_URL, WEBAPP_HOST, WEBAPP_PORT
from database import init_db
from xui_api import get_xui_cookie
from handlers import register_handlers

# Инициализация бота и диспетчера
bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# Регистрация обработчиков
register_handlers(dp)


async def on_startup(app: web.Application):
    """Действия при запуске приложения"""
    await init_db()  # инициализируем БД при старте
    await bot.set_webhook(WEBHOOK_URL)
    await get_xui_cookie()  # логинимся при старте


async def on_shutdown(app: web.Application):
    """Действия при остановке приложения"""
    await bot.delete_webhook()


def main():
    """Главная функция запуска"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    app = web.Application()
    SimpleRequestHandler(dp, bot).register(app, path="/webhook")
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)
    setup_application(app, dp, bot=bot)
    
    logging.info(f"🚀 Бот запущен на {WEBAPP_HOST}:{WEBAPP_PORT}")
    web.run_app(app, host=WEBAPP_HOST, port=WEBAPP_PORT)


if __name__ == "__main__":
    main()

