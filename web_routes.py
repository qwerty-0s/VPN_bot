"""HTTP-обработчики для веб-роутов бота"""
import logging
from aiohttp import web
from database import get_user_by_short_id
from config import FRONT_DOMAIN


async def handle_short_sub(request: web.Request) -> web.Response:
    """
    HTTP-обработчик для коротких ссылок /sub/{short_id}.
    Возвращает прямую vless:// ссылку в формате, который точно принимает v2rayNG.
    Формат соответствует рабочей ссылке: type=tcp&encryption=none&security=reality&pbk=...&fp=chrome&sni=...&sid=...&spx=%2F
    """
    short_id = request.match_info.get("short_id")
    if not short_id:
        return web.Response(status=400, text="short_id is required")

    row = await get_user_by_short_id(short_id)
    if not row:
        return web.Response(status=404, text="Link not found or expired")

    # row: (telegram_id, uuid, email, port, public_key, expiry_time, created_at, short_id)
    _, uuid_value, _, port, public_key, _, _, _ = row

    # Формируем vless:// ссылку в точном формате, как рабочая ссылка
    # Порядок параметров важен для совместимости с v2rayNG
    # Формат: type=tcp&encryption=none&security=reality&pbk=...&fp=chrome&sni=...&sid=...&spx=%2F
    vless_link = (
        f"vless://{uuid_value}@{FRONT_DOMAIN}:{port}"
        f"?type=tcp&encryption=none&security=reality"
        f"&pbk={public_key}&fp=chrome&sni=google.com"
        f"&sid=32a221&spx=%2F#Trial"
    )

    # Возвращаем прямую ссылку без base64
    # Добавляем перенос строки в конце (стандарт subscription формата)
    # v2rayNG принимает такой формат для импорта subscription
    return web.Response(
        text=vless_link + "\n",
        content_type="text/plain",
        charset="utf-8",
    )

