import logging
import asyncio
import aiohttp
from aiohttp import web
from database import get_user_by_short_id
from config import FRONT_DOMAIN, VPN_DOMAIN

# URL подписки находится на VPN сервере по порту 2096
# VPN_DOMAIN должен быть IP или домен VPN сервера
if VPN_DOMAIN:
    XUI_SUB_URL = f"http://{VPN_DOMAIN}:2096/sub/"
else:
    # Fallback на FRONT_DOMAIN если VPN_DOMAIN не установлен
    XUI_SUB_URL = f"http://{FRONT_DOMAIN}:2096/sub/"

async def handle_short_sub(request: web.Request) -> web.Response:
    """
    HTTP-обработчик, который получает конфиг подписки и возвращает его клиенту.
    Пользователь обращается по ссылке /sub/{short_id}, а бот достает данные из БД
    и получает конфиг с VPN сервера.
    """
    short_id = request.match_info.get("short_id")
    user_agent = request.headers.get('User-Agent', 'unknown')
    
    if not short_id:
        logging.warning(f"⚠️ Получен запрос /sub/ без short_id от {request.remote} (UA: {user_agent})")
        return web.Response(status=400, text="short_id is required")

    logging.info(f"📥 Запрос подписки: short_id={short_id}, IP={request.remote}, UA={user_agent}")

    # 1. Получаем пользователя из базы данных
    user = await get_user_by_short_id(short_id)
    if not user:
        logging.info(f"⚠️ Пользователь с short_id={short_id} не найден в БД")
        return web.Response(status=404, text="User not found")

    # 2. Используем short_id из БД
    sub_id = user.get('short_id')
    if not sub_id:
        logging.error(f"❌ short_id не найден для пользователя с telegram_id={user.get('telegram_id')}")
        return web.Response(status=500, text="Internal error: short_id not found")

    # 3. Формируем URL к подписке на VPN сервере
    target_url = f"{XUI_SUB_URL}{sub_id}"
    logging.debug(f"📝 Обращаюсь к VPN: {target_url}")

    try:
        # 4. Делаем запрос к VPN серверу
        async with aiohttp.ClientSession() as session:
            async with session.get(target_url, timeout=10, ssl=False) as resp:
                if resp.status == 200:
                    # Получаем содержимое конфига
                    content = await resp.text()
                    if not content:
                        logging.warning(f"⚠️ VPN вернула пустой ответ для short_id={short_id}")
                        return web.Response(status=502, text="Empty subscription config")
                    
                    logging.info(f"✅ Конфиг получен для short_id={short_id} (размер: {len(content)} байт)")
                    
                    # Возвращаем ответ в формате подписки
                    return web.Response(
                        text=content,
                        content_type="text/plain",
                        charset="utf-8",
                        headers={
                            "Subscription-Userinfo": resp.headers.get("Subscription-Userinfo", ""),
                            "Profile-Update-Interval": "24"
                        }
                    )
                elif resp.status == 404:
                    # Подписка не найдена на панели
                    error_text = await resp.text()
                    logging.warning(f"⚠️ VPN вернула 404 для url={target_url}. Ответ: {error_text[:100]}")
                    return web.Response(status=404, text="Subscription not found on server")
                else:
                    # Другая ошибка панели
                    error_text = await resp.text()
                    logging.error(f"❌ VPN вернула {resp.status} для short_id={short_id}. URL: {target_url}")
                    logging.error(f"   Ответ: {error_text[:200]}")
                    return web.Response(status=502, text=f"Server error: {resp.status}")
                    
    except asyncio.TimeoutError:
        logging.error(f"⏱️ Timeout при обращении к VPN (url: {target_url})")
        return web.Response(status=504, text="Server timeout")
    except Exception as e:
        logging.error(f"❌ Критическая ошибка при запросе к VPN (url: {target_url}): {e}", exc_info=True)
        return web.Response(status=500, text="Internal server error")