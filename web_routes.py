import logging
import aiohttp
from aiohttp import web
from database import get_user_by_short_id
from config import FRONT_DOMAIN

XUI_SUB_URL = f"http://{FRONT_DOMAIN}:2096/sub/"

async def handle_short_sub(request: web.Request) -> web.Response:
    """
    HTTP-обработчик, который проксирует запрос к подписке 3x-ui.
    Пользователь обращается к боту, а бот забирает данные из панели.
    """
    short_id = request.match_info.get("short_id")
    if not short_id:
        return web.Response(status=400, text="short_id is required")

    # 1. Получаем пользователя из базы данных (новая структура)
    user = await get_user_by_short_id(short_id)
    if not user:
        return web.Response(status=404, text="User not found")

    # 2. Извлекаем email и формируем subId как в xui_api.py
    email = user.get('email')
    sub_id = f"trial_{email[-6:]}" 

    # 3. Формируем прямой URL к подписке на панели 3x-ui
    target_url = f"{XUI_SUB_URL}{sub_id}"

    try:
        # 4. Делаем запрос к панели
        async with aiohttp.ClientSession() as session:
            async with session.get(target_url, timeout=5) as resp:
                if resp.status == 200:
                    # Получаем содержимое (обычно это Base64 строка)
                    content = await resp.text()
                    
                    # Возвращаем ответ в формате подписки
                    return web.Response(
                        text=content,
                        content_type="text/plain",
                        charset="utf-8",
                        headers={
                            "Subscription-Userinfo": resp.headers.get("Subscription-Userinfo", ""),
                            "Profile-Update-Interval": "1"
                        }
                    )
                elif resp.status == 404:
                    logging.error(f"❌ Панель вернула 404 для sub_id: {sub_id}. Проверьте Settings -> Sub Settings.")
                    return web.Response(status=404, text="Subscription not active in panel")
                else:
                    return web.Response(status=502, text="Panel error")
                    
    except Exception as e:
        logging.error(f"❌ Ошибка при обращении к панели: {e}")
        return web.Response(status=500, text="Internal server error")