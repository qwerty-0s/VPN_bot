import asyncio
import logging
from contextlib import AsyncExitStack, suppress
from urllib.parse import urlparse

from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramForbiddenError, TelegramNotFound
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import ClientSession, CookieJar, DummyCookieJar, web

from .domain import UnreachableUser
from .integrations.xui import XUI
from .integrations.yookassa import YooKassa
from .services import Service
from .settings import TARIFFS, Settings
from .storage import SQLStore
from .transport.http import register_routes
from .transport.telegram import profile_text, router


def create_app(settings):
    app = web.Application(client_max_size=64 * 1024)
    store = SQLStore(settings.database_url)
    bot = Bot(settings.token)
    dp = Dispatcher()

    async def lifecycle(app):
        async with AsyncExitStack() as stack:
            stack.push_async_callback(store.close)
            stack.push_async_callback(bot.session.close)
            await store.initialize()
            payment_session = await stack.enter_async_context(ClientSession(cookie_jar=DummyCookieJar()))
            panel_session = await stack.enter_async_context(ClientSession(cookie_jar=CookieJar(unsafe=True)))
            sub_session = await stack.enter_async_context(ClientSession(cookie_jar=DummyCookieJar()))
            gateway = YooKassa(payment_session, settings.shop_id, settings.shop_secret)
            panel = XUI(
                panel_session,
                settings.panel_url,
                settings.panel_user,
                settings.panel_password,
                settings.panel_verify_ssl,
                settings.panel_inbounds,
            )
            service = Service(
                store,
                gateway,
                panel,
                shop_id=settings.shop_id,
                test_payments=settings.test_payments,
                return_url=settings.return_url,
                tariffs=TARIFFS,
            )
            # Handlers/routes are installed before aiohttp freezes the router.
            dp.include_router(router(service, settings.public_url))
            register_routes(app, service, sub_session, settings.panel_sub_url)
            await bot.set_webhook(
                settings.webhook_url,
                secret_token=settings.telegram_secret,
                allowed_updates=dp.resolve_used_update_types(),
            )

            async def send(subscription):
                try:
                    await bot.send_message(
                        subscription.telegram_id,
                        "Оплата получена.\n"
                        + profile_text(subscription, settings.public_url, service.clock()),
                    )
                except (TelegramForbiddenError, TelegramNotFound) as exc:
                    raise UnreachableUser(str(exc)) from exc

            async def worker():
                while True:
                    try:
                        await service.reconcile()
                        await service.notify(send)
                    except Exception as exc:
                        logging.getLogger(__name__).warning("Reconciliation failed (%s)", type(exc).__name__)
                    await asyncio.sleep(30)

            task = asyncio.create_task(worker())
            try:
                yield
            finally:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

    app.cleanup_ctx.append(lifecycle)
    SimpleRequestHandler(dp, bot, secret_token=settings.telegram_secret, handle_in_background=False).register(
        app, path=urlparse(settings.webhook_url).path or "/webhook"
    )
    setup_application(app, dp, bot=bot)
    return app


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    # Access logs would expose bearer subscription links in URL paths.
    settings = Settings.load()
    web.run_app(create_app(settings), host=settings.host, port=settings.port, access_log=None)
