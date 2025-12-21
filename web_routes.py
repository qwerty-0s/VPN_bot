"""HTTP-обработчики для веб-роутов бота"""
import logging
from aiohttp import web
from database import get_user_by_short_id
from config import FRONT_DOMAIN
import base64

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
        f"?type=tcp"
        f"&encryption=none"
        f"&security=reality"
        f"&flow=xtls-rprx-vision"
        f"&pbk={public_key}"
        f"&fp=chrome"
        f"&sni=google.com"
        f"&sid=32a221ff"
        f"&headerType=none"
        f"#ProximaTrial"
    )
    
    if "\n" in vless_link or "\r" in vless_link:
        raise ValueError("VLESS link contains newline")


    payload = vless_link + "\n"   # перенос ТОЛЬКО здесь
    encoded = base64.b64encode(payload.encode("utf-8")).decode("ascii")

    return web.Response(
    text=encoded,
    content_type="text/plain",
    charset="utf-8",
    )

